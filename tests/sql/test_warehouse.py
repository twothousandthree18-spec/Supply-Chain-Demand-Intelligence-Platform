"""
Supply Chain & Demand Intelligence Platform
Phase 2 - Warehouse / ETL acceptance tests (pytest)

These tests are READ-ONLY: they run SELECT statements against the completed
PostgreSQL warehouse ('supply_chain_intelligence') built by the Phase 2
detached ETL (see src/etl/build_warehouse.py). They never modify data.

They verify the Phase 2 acceptance criteria:
  * schema/tables exist
  * dimension + fact row counts
  * key uniqueness / natural-key uniqueness
  * foreign-key / referential integrity (no orphans)
  * expected demand totals and price-row counts
  * reconciliation against Phase 1 baselines (reports/m5_profiling.json)
  * ETL run status == SUCCESS

Usage:
  .venv\\Scripts\\python -m pytest tests/sql -q
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from conftest import scalar  # noqa: E402

# ---- Phase 1 / M5 known baselines (from reports/m5_profiling.json) ----
PROF = json.load(open(REPO_ROOT / "reports" / "m5_profiling.json", "r", encoding="utf-8"))
EVAL = PROF["files"]["sales_train_evaluation.csv"]
EVAL_TOTAL_DEMAND = EVAL["total_demand"]                  # 66,927,173
EVAL_INT_ROWS = EVAL["rows"]                              # 30,490
EVAL_DAY_END = 1941
PRICES = PROF["files"]["sell_prices.csv"]
PRICE_ROWS = PRICES["rows"]                               # 6,841,121
PRICE_MAX = PRICES["sell_price_max"]                      # 107.32
N_PRODUCTS = EVAL["product_count"]                        # 3,049
N_STORES = EVAL["store_count"]                            # 10
N_DAYS = PROF["files"]["calendar.csv"]["rows"]            # 1,969
N_CATS = 3
N_DEPTS = 7

OBSERVED_FACT_EXPECTED = EVAL_INT_ROWS * EVAL_DAY_END     # 59,181,090


def _count(conn, table: str) -> int:
    return scalar(conn.cursor(), f"SELECT count(*) FROM {table}")


def _exists_table(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass(%s) IS NOT NULL",
        ("public." + table,),
    )
    r = cur.fetchone()[0]
    return bool(r)


# =====================================================================
# Schema / tables exist
# =====================================================================

def test_all_required_tables_exist(conn):
    required = [
        # dimensions
        "dim_date", "dim_product", "dim_store", "dim_category",
        "dim_department", "dim_event",
        # facts (all 7 from the Phase 0 architecture)
        "fact_daily_sales", "fact_weekly_price", "fact_product_store_demand",
        "fact_forecast", "fact_forecast_evaluation",
        "fact_inventory_simulation", "fact_replenishment_recommendation",
        # metadata / config
        "etl_run_log", "data_quality_results", "model_registry",
        "assumption_set",
        # staging
        "stg_calendar", "stg_sell_prices", "stg_sales_meta", "stg_sales_daily",
    ]
    missing = [t for t in required if not _exists_table(conn, t)]
    assert not missing, f"missing tables: {missing}"


def test_fact_has_provenance_columns(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='fact_daily_sales' AND column_name IN
              ('data_provenance','demand_source')""")
    cols = {r[0] for r in cur.fetchall()}
    assert {"data_provenance", "demand_source"} <= cols


# =====================================================================
# Dimension row counts
# =====================================================================

def test_dimension_counts(conn):
    assert _count(conn, "dim_product") == N_PRODUCTS
    assert _count(conn, "dim_store") == N_STORES
    assert _count(conn, "dim_date") == N_DAYS
    assert _count(conn, "dim_category") == N_CATS
    assert _count(conn, "dim_department") == N_DEPTS


def test_department_category_hierarchy(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT c.category_id, count(d.dept_surr_id)
        FROM dim_category c LEFT JOIN dim_department d
             ON d.category_surr_id = c.category_surr_id
        GROUP BY c.category_id ORDER BY 1""")
    rows = {c: n for c, n in cur.fetchall()}
    assert rows == {"FOODS": 3, "HOBBIES": 2, "HOUSEHOLD": 2}


def test_store_state_hierarchy(conn):
    cur = conn.cursor()
    cur.execute("SELECT state_id, count(*) FROM dim_store GROUP BY 1 ORDER BY 1")
    rows = {s: n for s, n in cur.fetchall()}
    assert rows == {"CA": 4, "TX": 3, "WI": 3}


# =====================================================================
# Fact row counts
# =====================================================================

def test_fact_daily_sales_count(conn):
    assert _count(conn, "fact_daily_sales") == OBSERVED_FACT_EXPECTED


def test_fact_weekly_price_count(conn):
    assert _count(conn, "fact_weekly_price") == PRICE_ROWS


# =====================================================================
# Key uniqueness
# =====================================================================

def test_dimension_natural_keys_unique(conn):
    cur = conn.cursor()
    for tbl, key in [
        ("dim_product", "product_id"),
        ("dim_store", "store_id"),
        ("dim_date", "date_id"),
        ("dim_category", "category_id"),
        ("dim_department", "dept_id"),
    ]:
        cur.execute(f"SELECT count(*)-count(DISTINCT {key}) FROM {tbl}")
        assert cur.fetchone()[0] == 0, f"dup natural key {tbl}.{key}"


def test_fact_key_uniqueness(conn):
    """Composite-key uniqueness is enforced by UNIQUE constraints (the schema
    forbids duplicate (product,store,date) and (product,store,week) rows, which
    is what guarantees the insert produced no duplicates). We verify the
    constraint exists on the exact composite key AND that the row count equals
    the full known Cartesian key space, which together prove both no-duplicate
    and no-gap. This avoids replaying a 59M-row GROUP BY on every run."""
    cur = conn.cursor()

    def unique_index_on(tbl, cols):
        cur.execute("""
            SELECT count(*) FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_class r ON r.oid = i.indexrelid
            WHERE i.indisunique AND c.relname = %s
              AND (SELECT string_agg(a.attname, ',' ORDER BY k.ordinality)
                     FROM unnest(i.indkey::int[]) WITH ORDINALITY k(attnum,ordinality)
                     JOIN pg_attribute a
                       ON a.attrelid = i.indrelid AND a.attnum = k.attnum) = %s
            """, (tbl, cols))
        return cur.fetchone()[0]

    # (1) the DB enforces both composite keys as UNIQUE
    assert unique_index_on("fact_daily_sales",
                           "product_surr_id,store_surr_id,date_id") == 1
    assert unique_index_on("fact_weekly_price",
                           "product_surr_id,store_surr_id,wm_yr_wk") == 1

    # (2) fact_daily_sales must cover the full key space (every product x store
    #     x observed day) => exactly matches no-duplicate and no-gap.
    cur.execute("""
        SELECT (SELECT count(*) FROM dim_product)
             * (SELECT count(*) FROM dim_store)
             * (SELECT count(DISTINCT date_id) FROM fact_daily_sales)
             = (SELECT count(*) FROM fact_daily_sales)""")
    assert cur.fetchone()[0] is True, "fact_daily_sales key space not fully covered"
    # fact_weekly_price: prices exist ONLY for (product,store,week) combos where
    # the item was sold, so it is NOT the full Cartesian space. Uniqueness is
    # enforced by the UNIQUE constraint (checked above) and the row count of the
    # fact equals the source sell_prices row count (no dup, no loss).
    assert _count(conn, "fact_weekly_price") == PRICE_ROWS


def test_fact_pk_columns_unique(conn):
    """PK uniqueness is enforced by the PRIMARY KEY index; verify it exists on
    exactly the surrogate PK column. Avoids a 59M-row DISTINCT scan."""
    cur = conn.cursor()

    def pk_column(tbl):
        cur.execute("""
            SELECT string_agg(a.attname, ',')
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_class r ON r.oid = i.indexrelid
            JOIN pg_constraint con ON con.conindid = i.indexrelid
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                                  AND a.attnum = ANY(i.indkey)
            WHERE c.relname = %s AND con.contype = 'p'""", (tbl,))
        return cur.fetchone()[0]

    assert pk_column("fact_daily_sales") == "sales_id"
    assert pk_column("fact_weekly_price") == "price_id"


def test_fk_constraints_defined(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_constraint
        WHERE contype='f' AND conrelid IN (
          'fact_daily_sales'::regclass,
          'fact_weekly_price'::regclass,
          'dim_department'::regclass,
          'dim_product'::regclass)""")
    assert cur.fetchone()[0] >= 5, "expected FK constraints on facts/dims"


# =====================================================================
# Referential integrity / no orphans
# =====================================================================

def test_no_orphan_sales_rows(conn):
    """Referential integrity is enforced by FK constraints: fact_daily_sales
    references dim_product, dim_store and dim_date, so the database rejects any
    row whose surrogate keys do not resolve to an existing dimension row. The
    successful ETL insert therefore guarantees zero orphans. We verify the
    exact FK mappings exist rather than replay a 59M-row anti-join."""
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM pg_constraint c
        JOIN pg_class c1 ON c1.oid = c.conrelid
        JOIN pg_class c2 ON c2.oid = c.confrelid
        WHERE c.contype='f'
          AND c1.relname='fact_daily_sales'
          AND c2.relname IN ('dim_product','dim_store','dim_date')
        GROUP BY 1 HAVING count(DISTINCT c2.relname) = 3""")
    assert cur.fetchone(), "fact_daily_sales missing FK to product/store/date"


def test_no_orphan_price_rows(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM pg_constraint c
        JOIN pg_class c1 ON c1.oid = c.conrelid
        JOIN pg_class c2 ON c2.oid = c.confrelid
        WHERE c.contype='f'
          AND c1.relname='fact_weekly_price'
          AND c2.relname IN ('dim_product','dim_store')
        GROUP BY 1 HAVING count(DISTINCT c2.relname) = 2""")
    assert cur.fetchone(), "fact_weekly_price missing FK to product/store"


def test_product_department_chain(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM dim_product p
        LEFT JOIN dim_department de ON de.dept_surr_id = p.dept_surr_id
        LEFT JOIN dim_category c    ON c.category_surr_id = p.category_surr_id
        WHERE de.dept_surr_id IS NULL OR c.category_surr_id IS NULL""")
    assert cur.fetchone()[0] == 0, "orphan product->dept/cat chain"


# =====================================================================
# Expected demand / price values
# =====================================================================

def test_total_observed_demand(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT sum(units_sold) FROM fact_daily_sales
        WHERE demand_source='observed'""")
    assert cur.fetchone()[0] == EVAL_TOTAL_DEMAND, "observed total demand mismatch"


def test_units_non_negative(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM fact_daily_sales WHERE units_sold < 0")
    assert cur.fetchone()[0] == 0, "negative units in fact_daily_sales"


def test_price_range(conn):
    cur = conn.cursor()
    cur.execute("SELECT min(sell_price), max(sell_price) FROM fact_weekly_price")
    lo, hi = cur.fetchone()
    assert float(lo) == 0.01 and float(hi) == PRICE_MAX, f"price range [{lo},{hi}]"


# =====================================================================
# Reconciliation vs Phase 1 baselines
# =====================================================================

def test_reconciliation_vs_phase1(conn):
    """Observed facts reconcile exactly against the Phase 1 profiling numbers."""
    assert _count(conn, "dim_product") == N_PRODUCTS
    assert _count(conn, "dim_store") == N_STORES
    assert _count(conn, "dim_date") == N_DAYS
    assert _count(conn, "fact_weekly_price") == PRICE_ROWS
    cur = conn.cursor()
    cur.execute("SELECT sum(units_sold) FROM fact_daily_sales WHERE demand_source='observed'")
    assert cur.fetchone()[0] == EVAL_TOTAL_DEMAND


def test_etl_run_success(conn):
    """The most recent build_warehouse run must have completed as SUCCESS."""
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, status FROM etl_run_log
        WHERE pipeline='build_warehouse'
        ORDER BY run_id DESC LIMIT 1""")
    run_id, status = cur.fetchone()
    assert status == "success", f"latest ETL run {run_id} status={status}"
    cur.execute("SELECT records_loaded FROM etl_run_log WHERE run_id=%s", (run_id,))
    assert cur.fetchone()[0] == OBSERVED_FACT_EXPECTED
