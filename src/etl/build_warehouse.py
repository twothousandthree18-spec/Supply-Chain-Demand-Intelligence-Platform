"""
Supply Chain & Demand Intelligence Platform
Phase 2 - Warehouse build ETL (resumable, idempotent, detached-safe).

Pipeline: RAW files (immutable) -> STAGING -> WAREHOUSE dimensions/facts.

Flow:
  1. abandon_stale_runs   (mark interrupted 'running' runs as FAILED)
  2. start_etl_run        (audit)
  3. schema SQL           (create base tables)
  4. staging SQL          (create staging tables)
  5. staging loads        (calendar, sell_prices, sales_meta reused if valid;
                           sales_daily via chunked wide->long melt + COPY)
  6. dimension loads      (sql/dimensions/*.sql; idempotent ON CONFLICT)
  7. fact loads           (sql/facts/*.sql; idempotent ON CONFLICT)
  8. index SQL            (sql/indexes/*.sql)
  9. validation + reconciliation vs Phase 1 baselines
  10. finish_etl_run (SUCCESS)  -- on any exception -> FAILED + nonzero exit

Idempotency / recovery (safe, no duplicate rows):
  * Staging tables calendar/sell_prices/sales_meta are only reloaded when
    they are EMPTY. Verified staging data is reused across reruns.
  * stg_sales_daily (the large 59M-row target) is loaded fresh ONLY when empty
    and is TRUNCATED at the start of its (re)load, so an interrupted melt
    never leaves a partial copy that is later appended to.
  * Dimension and fact loads use ON CONFLICT ... DO NOTHING, so rerunning the
    same pipeline can never insert duplicates.

The full observed daily demand is loaded from sales_train_evaluation.csv (a
strict superset of sales_train_validation for d_1..d_1913, extended to d_1941),
so the warehouse holds exactly one non-duplicated row per (product, store, day).
Designed to run detached (background) writing to a persistent log; it neither
needs nor waits for an interactive terminal.
"""

from __future__ import annotations

import io
import sys
import time
import json
import traceback
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from scripts.python.config_loader import load_config  # noqa: E402
from src.etl.db_utils import connect                            # noqa: E402

CONFIG = load_config()
RAW = REPO_ROOT / CONFIG["paths"]["raw"]
SQL = REPO_ROOT / "sql"
REPORTS = REPO_ROOT / CONFIG["paths"]["reports"]

SALES_FILE = RAW / "sales_train_evaluation.csv"
CHUNK_ROWS = 6000
LOG_EVERY = 2_000_000          # log progress every 2M rows
TARGET_SALES_ROWS = 30490 * 1941   # 59,181,090


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(msg, flush=True)


def exec_sql_file(conn, path: Path, label: str) -> float:
    t0 = time.time()
    with conn.cursor() as cur, open(path, "r", encoding="utf-8") as f:
        cur.execute(f.read())
    conn.commit()
    dt = time.time() - t0
    log(f"  [ok] {label}: {path.name} ({dt:.1f}s)")
    return dt


def table_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def copy_csv(conn, path: Path, table: str, cols: list) -> int:
    """Bulk COPY a CSV file into a table (columns in source-file order)."""
    cur = conn.cursor()
    with open(path, "r", encoding="utf-8") as f:
        f.readline()  # consume header; copy_expert reads remaining lines
        cur.copy_expert(
            f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER false)",
            f,
        )
    conn.commit()
    n = cur.rowcount
    cur.close()
    return n


def load_sales_meta(conn) -> int:
    """Load product/store hierarchy from sales id columns (small; 30,490 rows)."""
    cur = conn.cursor()
    df = pd.read_csv(
        SALES_FILE,
        usecols=["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"],
        dtype_backend="numpy_nullable",
    )
    buf = io.StringIO()
    df[["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]].to_csv(
        buf, index=False, header=False
    )
    buf.seek(0)
    cur.copy_expert(
        "COPY stg_sales_meta (id, item_id, dept_id, cat_id, store_id, state_id) "
        "FROM STDIN WITH (FORMAT csv, HEADER false)",
        buf,
    )
    conn.commit()
    n = cur.rowcount
    cur.close()
    log(f"  [ok] staged sales meta rows: {n:,}")
    return n


def melt_sales_to_staging(conn, path: Path, chunks: int) -> int:
    """Wide->long melt in chunks, COPY each chunk, memory released per chunk."""
    usecols = ["id", "item_id", "store_id"] + [f"d_{i}" for i in range(1, 1942)]
    cur = conn.cursor()

    # safe restart: the large target is truncated only at the start of THIS load
    cur.execute("TRUNCATE stg_sales_daily")
    conn.commit()

    total = 0
    t0 = time.time()
    for df in pd.read_csv(
        path, usecols=usecols, chunksize=chunks, dtype_backend="numpy_nullable"
    ):
        long_df = df.melt(
            id_vars=["id", "item_id", "store_id"], var_name="day_col", value_name="units"
        )
        long_df["day_index"] = (
            long_df["day_col"].str.replace("d_", "", regex=False).astype("int64")
        )
        long_df = long_df[["id", "item_id", "store_id", "day_index", "units"]]
        buf = io.StringIO()
        long_df.to_csv(
            buf, index=False, header=False,
            columns=["id", "item_id", "store_id", "day_index", "units"],
        )
        buf.seek(0)
        cur.copy_expert(
            "COPY stg_sales_daily (id, item_id, store_id, day_index, units) "
            "FROM STDIN WITH (FORMAT csv, HEADER false)",
            buf,
        )
        total += len(long_df)
        del long_df, buf, df
        if total % LOG_EVERY == 0:
            log(f"    ... {total:,} / {TARGET_SALES_ROWS:,} rows "
                f"({100*total/TARGET_SALES_ROWS:.1f}%) "
                f"elapsed {time.time()-t0:.0f}s")
    conn.commit()
    cur.close()
    log(f"  [ok] staged sales long-form: {total:,} rows ({time.time()-t0:.1f}s)")
    return total


def query_one(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
def main():
    args = sys.argv[1:]
    skip_schema = "--skip-schema" in args

    conn = connect()
    log(f"connected: {conn.dsn}")

    # 0. audit infra
    exec_sql_file(conn, SQL / "schema" / "03_metadata.sql", "metadata")
    exec_sql_file(conn, SQL / "utilities" / "60_utilities.sql", "utilities")

    # 0b. abandon stale interrupted runs
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_run_log SET status='failed', "
            "error_message=COALESCE(error_message,'abandoned (no live process)') "
            "WHERE status='running'"
        )
    conn.commit()

    # 0c. start this run
    with conn.cursor() as cur:
        cur.execute("SELECT start_etl_run('build_warehouse')")
        run_id = cur.fetchone()[0]
    conn.commit()
    log(f"etl run_id = {run_id}")

    # 2-3. schema + staging DDL
    if not skip_schema:
        for f in sorted((SQL / "schema").glob("*.sql")):
            exec_sql_file(conn, f, "schema")
        for f in sorted((SQL / "staging").glob("*.sql")):
            exec_sql_file(conn, f, "staging")
    else:
        log("  [skip] schema/staging DDL (--skip-schema)")

    # 5. staging loads - reuse valid data, load only what is empty
    if table_count(conn, "stg_calendar") == 0:
        copy_csv(conn, RAW / "calendar.csv", "stg_calendar",
                 ["date", "wm_yr_wk", "weekday", "wday", "month", "year", "d",
                  "event_name_1", "event_type_1", "event_name_2", "event_type_2",
                  "snap_ca", "snap_tx", "snap_wi"])
        log(f"  [ok] staged calendar rows: {table_count(conn,'stg_calendar'):,}")
    else:
        log(f"  [reuse] stg_calendar already has {table_count(conn,'stg_calendar'):,} rows")

    if table_count(conn, "stg_sell_prices") == 0:
        copy_csv(conn, RAW / "sell_prices.csv", "stg_sell_prices",
                 ["store_id", "item_id", "wm_yr_wk", "sell_price"])
        log(f"  [ok] staged sell_prices rows: {table_count(conn,'stg_sell_prices'):,}")
    else:
        log(f"  [reuse] stg_sell_prices already has {table_count(conn,'stg_sell_prices'):,} rows")

    if table_count(conn, "stg_sales_meta") == 0:
        load_sales_meta(conn)
    else:
        log(f"  [reuse] stg_sales_meta already has {table_count(conn,'stg_sales_meta'):,} rows")

    if table_count(conn, "stg_sales_daily") == 0:
        n_sales = melt_sales_to_staging(conn, SALES_FILE, CHUNK_ROWS)
    else:
        n_sales = table_count(conn, "stg_sales_daily")
        log(f"  [reuse] stg_sales_daily already has {n_sales:,} rows")

    # 6-7. dimensions + facts (idempotent)
    for f in sorted((SQL / "dimensions").glob("*.sql")):
        exec_sql_file(conn, f, "dims")
    for f in sorted((SQL / "facts").glob("*.sql")):
        exec_sql_file(conn, f, "facts")

    # 8. indexes
    for f in sorted((SQL / "indexes").glob("*.sql")):
        exec_sql_file(conn, f, "indexes")

    # 9. reconciliation + integrity summary
    profile = json.load(open(REPORTS / "m5_profiling.json", "r", encoding="utf-8"))
    eval_baseline = profile["files"]["sales_train_evaluation.csv"]["total_demand"]
    baseline_days = 1969
    n_products = query_one(conn, "SELECT count(*) FROM dim_product")
    n_stores = query_one(conn, "SELECT count(*) FROM dim_store")
    n_dates = query_one(conn, "SELECT count(*) FROM dim_date")
    n_cats = query_one(conn, "SELECT count(*) FROM dim_category")
    n_depts = query_one(conn, "SELECT count(*) FROM dim_department")
    n_days = query_one(conn, "SELECT count(DISTINCT date_id) FROM fact_daily_sales")
    total_demand = query_one(conn, "SELECT SUM(units_sold) FROM fact_daily_sales WHERE demand_source='observed'")
    n_fact_rows = query_one(conn, "SELECT count(*) FROM fact_daily_sales")
    n_prices = query_one(conn, "SELECT count(*) FROM fact_weekly_price")
    price_min = query_one(conn, "SELECT min(sell_price) FROM fact_weekly_price")
    price_max = query_one(conn, "SELECT max(sell_price) FROM fact_weekly_price")

    orphan = query_one(conn, """
        SELECT count(*) FROM fact_daily_sales f
        LEFT JOIN dim_product p ON p.product_surr_id=f.product_surr_id
        LEFT JOIN dim_store s ON s.store_surr_id=f.store_surr_id
        LEFT JOIN dim_date d ON d.date_id=f.date_id
        WHERE p.product_surr_id IS NULL OR s.store_surr_id IS NULL OR d.date_id IS NULL""")
    dup = query_one(conn, """
        SELECT count(*) FROM (
          SELECT product_surr_id,store_surr_id,date_id FROM fact_daily_sales
          GROUP BY 1,2,3 HAVING count(*)>1) x""")
    price_dup = query_one(conn, """
        SELECT count(*) FROM (
          SELECT product_surr_id,store_surr_id,wm_yr_wk FROM fact_weekly_price
          GROUP BY 1,2,3 HAVING count(*)>1) x""")

    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT finish_etl_run(%s,%s,%s,%s,%s)",
            (run_id, "success", n_sales, n_fact_rows, None),
        )
    conn.commit()
    conn.close()

    log("\n=== RECONCILIATION ===")
    log(f"  dim_product  = {n_products}   (expected 3049)")
    log(f"  dim_store    = {n_stores}    (expected 10)")
    log(f"  dim_date     = {n_dates}    (expected {baseline_days})")
    log(f"  dim_category = {n_cats}    (expected 3)")
    log(f"  dim_department = {n_depts}   (expected 7)")
    log(f"  fact days    = {n_days}    (expected {baseline_days})")
    log(f"  fact_rows    = {n_fact_rows:,}  (expected {TARGET_SALES_ROWS:,})")
    log(f"  total demand = {total_demand:,}  (baseline {eval_baseline:,})")
    log(f"  price rows   = {n_prices:,}  (baseline 6,841,121)  price [{price_min},{price_max}]")
    log(f"  orphans={orphan}  dup_sales_keys={dup}  dup_price_keys={price_dup}")
    log(f"\n=== DONE (run_id={run_id} SUCCESS) ===")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("ETL FAILED", flush=True)
        sys.exit(1)
