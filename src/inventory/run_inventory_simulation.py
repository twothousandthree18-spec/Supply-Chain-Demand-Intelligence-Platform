"""
Supply Chain & Demand Intelligence Platform
Phase 3E - Inventory simulation driver.

Simulates every product/store series under the locked assumption set
(src/inventory/config.py, persisted to `assumption_set`) over the Phase 3D
forecast horizon (days 1942-1969, 28 days) and writes daily simulated inventory
traces to `fact_inventory_simulation`.

Inputs (bounded, no 59M observed-fact scan):
  * per-series demand moments  <- fact_demand_analysis (mean_daily_units,
                                 std_daily_units) already materialized in Phase 3C
  * per-series forecast demand <- fact_forecast (is_final, days 1942-1969), the
                                 Phase 3D final forecasts
Outputs (all data_provenance = 'simulated'):
  * assumption_set      - the baseline assumption row (idempotent upsert)
  * fact_inventory_simulation - 28 daily records per series (30,490 x 28)
  * printed run/risk summary

Resumable/idempotent: rows for the assumption set are deleted then re-inserted,
so a re-run overwrites cleanly without duplicating. Writes are batched with
periodic commits (never one giant transaction). Run status is logged to
etl_run_log (pipeline='inventory_simulation'); an interrupted run is marked
failed on the next invocation (mirrors run_forecasting / run_demand_analysis).

Run with `--pilot-only` to validate the FULL production path (same sizing,
same engine, same validation) on the top-N representative series WITHOUT any
database writes. Output captured to reports/PHASE_3E_PILOT_OUTPUT.txt.
"""

from __future__ import annotations

import argparse
import time
from collections import deque

import numpy as np
import pandas as pd

from src.etl.db_utils import connect
from src.inventory import config
from src.inventory.simulation import policy_from_aggregates, simulate_series

PIPELINE = "inventory_simulation"


# --------------------------------------------------------------------------- #
# Small helpers (mirror run_forecasting.py)
# --------------------------------------------------------------------------- #
def fetch(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def to_native(v):
    if v is None or isinstance(v, (str, bytes)):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        f = float(v)
        return None if np.isnan(f) else f
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _round(v, digits=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(f"{float(v):.{digits}f}")


def _pairs_sql(pairs):
    return ",".join(f"({int(a)},{int(b)})" for a, b in pairs)


# --------------------------------------------------------------------------- #
# Bounded pulls (never scan fact_daily_sales)
# --------------------------------------------------------------------------- #
def pull_sizing(conn, pairs=None):
    """Per-series demand moments from fact_demand_analysis (30,490 rows max)."""
    where = "WHERE analysis_window='observed_full'"
    if pairs is not None:
        where += f" AND (product_surr_id, store_surr_id) IN ({_pairs_sql(pairs)})"
    df = fetch(conn, f"""
        SELECT product_surr_id, store_surr_id, total_units,
               mean_daily_units, std_daily_units
        FROM fact_demand_analysis
        {where}
    """)
    for col in ("total_units", "mean_daily_units", "std_daily_units"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def pull_forecasts(conn, pairs=None):
    """Final Phase 3D forecasts for days [1942,1969] (one row per series-day)."""
    where = (
        f"WHERE is_final=TRUE AND forecast_date BETWEEN {config.HORIZON_START_DAY} "
        f"AND {config.HORIZON_END_DAY}"
    )
    if pairs is not None:
        where += f" AND (product_surr_id, store_surr_id) IN ({_pairs_sql(pairs)})"
    df = fetch(conn, f"""
        SELECT product_surr_id, store_surr_id, forecast_date, forecast_value
        FROM fact_forecast
        {where}
        ORDER BY product_surr_id, store_surr_id, forecast_date
    """)
    df["forecast_value"] = pd.to_numeric(df["forecast_value"], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# Series-level helpers
# --------------------------------------------------------------------------- #
def build_policy(mean_daily, std_daily):
    """InventoryPolicy from Phase 3C demand moments (aggregates, no history)."""
    mean = float(mean_daily) if not pd.isna(mean_daily) else 0.0
    std = float(std_daily) if not pd.isna(std_daily) else 0.0
    return policy_from_aggregates(mean, std)


def forecast_array(g):
    """Ordered 28-day forecast vector for one (product, store) group."""
    g = g.sort_values("forecast_date")
    arr = g["forecast_value"].to_numpy(dtype=np.float64)
    if np.any(np.isnan(arr)):
        arr = np.nan_to_num(arr, nan=0.0)
    if arr.shape[0] != config.HORIZON_DAYS:
        raise ValueError(f"expected {config.HORIZON_DAYS} forecast days, got {arr.shape[0]}")
    return arr


def series_rows(assumption_set_id, pid, sid, result):
    rows = []
    for d in result.days:
        rows.append(
            (assumption_set_id, int(pid), int(sid), int(d.day_id),
             _round(d.starting_inventory), _round(d.demand_forecast),
             _round(d.lead_time_demand), _round(d.safety_stock),
             _round(d.reorder_point), _round(d.inventory_position),
             _round(d.on_hand), _round(d.orders_placed),
             _round(d.reorder_qty), bool(d.projected_stockout),
             _round(d.stockout_units), _round(d.excess_inventory),
             _round(d.days_of_inventory), _round(d.service_level_achieved, 6),
             config.DATA_PROVENANCE_SIMULATED))
    return rows


_SIM_INSERT = (
    "INSERT INTO fact_inventory_simulation "
    "(assumption_set_id, product_surr_id, store_surr_id, day_id, "
    " starting_inventory, demand_forecast, lead_time_demand, safety_stock, "
    " reorder_point, inventory_position, on_hand, orders_placed, reorder_qty, "
    " projected_stockout, stockout_units, excess_inventory, days_of_inventory, "
    " service_level_achieved, data_provenance) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


# --------------------------------------------------------------------------- #
# Independent per-series validation: replay the daily state machine from the
# emitted records (transitions, reorder triggers, lead-time arrivals,
# backorders, stockouts). Catches any drift between the engine and the records.
# --------------------------------------------------------------------------- #
def validate_trace(pid, sid, policy, records):
    lead = int(round(policy.lead_time_days))
    on_hand = policy.starting_inventory
    on_order = 0.0
    backorder = 0.0
    pending = deque()
    order_days = 0
    stockout_days = 0
    total_stockout_units = 0.0
    excess_days = 0
    arrivals = 0.0

    for rec in records:
        # 1. recorded starting_inventory is the PRE-arrival on-hand; snapshot
        #    it before any replenishment lands at the start of this day.
        start_on_hand = on_hand
        while pending and pending[0][0] == rec.day_id:
            _, qty = pending.popleft()
            on_hand += qty
            on_order -= qty      # in-flight order has now landed
            arrivals += qty
        if abs(rec.starting_inventory - round(start_on_hand, 4)) > 0.011:
            raise AssertionError(
                f"({pid},{sid}) day {rec.day_id}: starting_inventory "
                f"{rec.starting_inventory} != replayed {start_on_hand:.4f}")

        # 2. serve demand + carried backorder
        total = rec.demand_forecast + backorder
        fulfilled = min(on_hand, total)
        unmet = total - fulfilled
        on_hand -= fulfilled
        backorder = unmet

        # 3. reorder if position <= reorder point
        position = on_hand + on_order - backorder
        order_qty = policy.reorder_quantity
        placed = order_qty if position <= policy.reorder_point and order_qty > 0 else 0.0
        if placed > 0:
            on_order += order_qty
            order_days += 1
            pending.append((rec.day_id + lead, order_qty))
        placed_mark = 1.0 if placed > 0 else 0.0
        if abs(rec.orders_placed - placed_mark) > 1e-9 or \
           abs(rec.reorder_qty - (order_qty if placed > 0 else 0.0)) > 1e-3:
            raise AssertionError(
                f"({pid},{sid}) day {rec.day_id}: reorder activity mismatch")

        end_position = on_hand + on_order - backorder
        if abs(rec.on_hand - round(on_hand, 4)) > 0.011:
            raise AssertionError(
                f"({pid},{sid}) day {rec.day_id}: on_hand {rec.on_hand} != "
                f"replayed {on_hand:.4f}")
        if abs(rec.inventory_position - round(end_position, 4)) > 0.011:
            raise AssertionError(
                f"({pid},{sid}) day {rec.day_id}: inventory_position "
                f"{rec.inventory_position} != replayed {end_position:.4f}")

        if unmet > 0:
            stockout_days += 1
            total_stockout_units += unmet
        if rec.excess_inventory > 0:
            excess_days += 1

    demand_total = sum(r.demand_forecast for r in records)
    fill_rate = 1.0 - backorder / demand_total if demand_total > 0 else 1.0
    return {
        "product_surr_id": int(pid), "store_surr_id": int(sid),
        "expected_daily_demand": policy.expected_daily_demand,
        "safety_stock": policy.safety_stock,
        "reorder_point": policy.reorder_point,
        "reorder_quantity": policy.reorder_quantity,
        "starting_inventory": policy.starting_inventory,
        "order_days": order_days,
        "arrivals": round(arrivals, 4),
        "stockout_days": stockout_days,
        "stockout_units": round(total_stockout_units, 4),
        "excess_days": excess_days,
        "fill_rate": round(fill_rate, 6),
        "service_level": round(1.0 - stockout_days / len(records), 6),
    }


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def upsert_assumption_set(conn):
    a = config.ASSUMPTION_SET_ROWS[config.ASSUMPTION_SET_NAME]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assumption_set "
            "(name, description, starting_inventory_rule, supplier_lead_time_days, "
            " service_level, safety_stock_formula, reorder_policy, "
            " reorder_quantity_rule, demand_adjustment) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (name) DO UPDATE SET "
            "  description=EXCLUDED.description, "
            "  starting_inventory_rule=EXCLUDED.starting_inventory_rule, "
            "  supplier_lead_time_days=EXCLUDED.supplier_lead_time_days, "
            "  service_level=EXCLUDED.service_level, "
            "  safety_stock_formula=EXCLUDED.safety_stock_formula, "
            "  reorder_policy=EXCLUDED.reorder_policy, "
            "  reorder_quantity_rule=EXCLUDED.reorder_quantity_rule, "
            "  demand_adjustment=EXCLUDED.demand_adjustment, "
            "  is_active=TRUE "
            "RETURNING assumption_set_id",
            (a["name"], a["description"], a["starting_inventory_rule"],
             to_native(a["supplier_lead_time_days"]), to_native(a["service_level"]),
             a["safety_stock_formula"], a["reorder_policy"],
             a["reorder_quantity_rule"], to_native(a["demand_adjustment"])),
        )
        assumption_set_id = cur.fetchone()[0]
    conn.commit()
    return int(assumption_set_id)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def simulate_all(sizing, fcast_by_key, on_series=None):
    """Run the engine over every series; return (metrics, iterator of row lists).

    `on_series` is an optional streaming sink for production row lists.
    """
    metrics = []
    for _, r in sizing.iterrows():
        pid, sid = int(r["product_surr_id"]), int(r["store_surr_id"])
        g = fcast_by_key.get((pid, sid))
        if g is None:
            raise ValueError(f"({pid},{sid}): no final forecast rows found")
        policy = build_policy(r["mean_daily_units"], r["std_daily_units"])
        fc = forecast_array(g)
        result = simulate_series(fc, policy=policy,
                                 start_day=config.HORIZON_START_DAY)
        m = validate_trace(pid, sid, policy, result.days)
        metrics.append(m)
        if on_series is not None:
            on_series(pid, sid, result)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Phase 3E inventory simulation")
    parser.add_argument("--pilot-only", action="store_true",
                        help="validate the full path on the top-N representative series; "
                             "no DB writes")
    parser.add_argument("--top-n", type=int, default=None,
                        help="pilot subset size (default config.PILOT_TOP_N)")
    args = parser.parse_args()
    top_n = args.top_n or config.PILOT_TOP_N

    conn = connect()
    conn.set_client_encoding("UTF8")

    run_id = None
    if not args.pilot_only:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE etl_run_log SET status='failed', error_message='abandoned (no live process)' "
                "WHERE status='running' AND pipeline=%s", (PIPELINE,))
        with conn.cursor() as cur:
            cur.execute("SELECT start_etl_run(%s)", (PIPELINE,))
            run_id = cur.fetchone()[0]
        conn.commit()

    print(f"[inventory_simulation] run_id={run_id} pilot_only={args.pilot_only} "
          f"top_n={top_n}")
    t0 = time.time()

    try:
        # ---------------- sizing + (pilot) subset selection ----------------- #
        sizing = pull_sizing(conn)
        if args.pilot_only:
            sizing = (sizing.sort_values("total_units", ascending=False)
                          .head(top_n).reset_index(drop=True))
            pairs = list(zip(sizing["product_surr_id"].astype(int),
                             sizing["store_surr_id"].astype(int)))
            sizing = sizing[sizing[["product_surr_id", "store_surr_id"]]
                           .apply(tuple, axis=1).isin(pairs)].reset_index(drop=True)
        print(f"  ... {len(sizing):,} series sized from fact_demand_analysis")

        # ---------------- forecast pull (bounded) -------------------------- #
        fcast = pull_forecasts(conn, pairs=None if not args.pilot_only else pairs)
        print(f"  ... {len(fcast):,} final forecast rows pulled "
              f"([{config.HORIZON_START_DAY},{config.HORIZON_END_DAY}])")
        fcast_by_key = {k: g for k, g in fcast.groupby(
            ["product_surr_id", "store_surr_id"])}

        # ---------------- pilot: validate + report, no DB ------------------ #
        if args.pilot_only:
            print("  ... simulating + independently validating")
            metrics = simulate_all(sizing, fcast_by_key)
            print(f"    simulated {len(metrics):,} series (all traces validated)")

            # engine determinism spot check: re-run first series and compare
            _spot_check_determinism(sizing, fcast_by_key, metrics)

            _print_pilot_report(metrics)
            print(f"[ok] pilot-only complete; no DB writes. elapsed={time.time()-t0:.1f}s")
            conn.close()
            return

        # ---------------- production --------------------------------------- #
        assumption_set_id = upsert_assumption_set(conn)
        print(f"  ... assumption_set row ensured (id={assumption_set_id})")

        total_days = len(sizing) * config.HORIZON_DAYS
        print("  ... clearing prior simulated rows for this assumption set (idempotent)")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fact_inventory_simulation "
                        "WHERE assumption_set_id = %s", (assumption_set_id,))
        conn.commit()

        print("  ... simulating all series (batched, resumable)")
        written = _write_production(conn, assumption_set_id, sizing, fcast_by_key)
        if written != total_days:
            raise RuntimeError(f"wrote {written:,} rows, expected {total_days:,}")
        print(f"    {written:,} simulated day-rows written (28 x {len(sizing):,} series)")

        with conn.cursor() as cur:
            cur.execute("SELECT finish_etl_run(%s,'success',%s,%s)",
                        (run_id, written, written))
        conn.commit()
        print(f"[ok] inventory simulation complete in {time.time()-t0:.1f}s")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        if run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT finish_etl_run(%s,'failed',0,0,%s)",
                                (run_id, str(e)))
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        conn.close()


def _write_production(conn, assumption_set_id, sizing, fcast_by_key):
    """Batched, idempotent write of every simulated daily record (30,490x28).

    Records are buffered per-series and flushed every `chunk` rows; commits
    happen every `chunk * commit_every` rows, so there is never a single giant
    transaction and an interrupted run is fully resumable (rows for the
    assumption set are deleted on the next run).
    """
    chunk = 5000
    commit_every = 8
    cur = conn.cursor()
    buf = []
    written = 0
    total = 0

    def add(pid, sid, result):
        nonlocal written, total
        buf.extend(series_rows(assumption_set_id, pid, sid, result))
        written += config.HORIZON_DAYS
        total += config.HORIZON_DAYS
        if len(buf) >= chunk:
            cur.executemany(_SIM_INSERT, buf)
            buf.clear()
            if total % (chunk * commit_every) == 0:
                conn.commit()

    try:
        simulate_all(sizing, fcast_by_key, on_series=add)
        if buf:
            cur.executemany(_SIM_INSERT, buf)
        conn.commit()
    finally:
        cur.close()
    return written


def _spot_check_determinism(sizing, fcast_by_key, metrics):
    """Re-run the first pilot series and confirm byte-identical records."""
    if not len(sizing):
        return
    r0 = sizing.iloc[0]
    pid, sid = int(r0["product_surr_id"]), int(r0["store_surr_id"])
    policy = build_policy(r0["mean_daily_units"], r0["std_daily_units"])
    fc = forecast_array(fcast_by_key[(pid, sid)])
    first = series_rows(0, pid, sid,
                        simulate_series(fc, policy=policy,
                                        start_day=config.HORIZON_START_DAY))
    second = series_rows(0, pid, sid,
                         simulate_series(fc, policy=policy,
                                         start_day=config.HORIZON_START_DAY))
    assert len(first) == config.HORIZON_DAYS
    assert all(a == b for a, b in zip(first, second)), "non-deterministic output!"
    assert all(a[18] == config.DATA_PROVENANCE_SIMULATED for a in first)
    m0 = metrics[0]
    assert m0["reorder_point"] == round(policy.reorder_point, 6)
    print(f"    determinism: first series ({pid},{sid}) re-ran byte-identical "
          f"({len(first)} records, provenance simulated)")


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _print_pilot_report(metrics):
    df = pd.DataFrame(metrics)
    print("\n" + "=" * 92)
    print("PHASE 3E REPRESENTATIVE PILOT - per-series trace (top-N by lifetime units)")
    print(f"assumption_set='{config.ASSUMPTION_SET_NAME}' "
          f"horizon=[{config.HORIZON_START_DAY},{config.HORIZON_END_DAY}] "
          f"service_level_target={config.SERVICE_LEVEL:.0%}")
    print("=" * 92)
    head = df.head(min(16, len(df))).copy()
    for col in ("expected_daily_demand", "safety_stock", "reorder_point",
                "reorder_quantity", "starting_inventory", "arrivals",
                "stockout_units"):
        head[col] = head[col].map(lambda v: f"{v:,.3f}")
    for col in ("order_days", "stockout_days", "excess_days"):
        head[col] = head[col].map(lambda v: f"{v:.0f}")
    for col in ("fill_rate", "service_level"):
        head[col] = head[col].map(lambda v: f"{v:.4f}")
    print(head.to_string(index=False))

    print("\n" + "-" * 92)
    print("AGGREGATE (across pilot series)")
    print(f"  series simulated                     : {len(df):,}")
    print(f"  total day-rows                       : {len(df) * config.HORIZON_DAYS:,}")
    print(f"  reorder triggers (series-days)       : {int(df['order_days'].sum()):,}")
    print(f"  replenishment arrivals (units)       : {df['arrivals'].sum():,.2f}")
    print(f"  stockout days (series-days)          : {int(df['stockout_days'].sum()):,}")
    print(f"  stockout units                       : {df['stockout_units'].sum():,.2f}")
    print(f"  excess-inventory days (series-days)  : {int(df['excess_days'].sum()):,}")
    print(f"  mean fill rate                       : {df['fill_rate'].mean():.4f} "
          f"(min {df['fill_rate'].min():.4f}, max {df['fill_rate'].max():.4f})")
    print(f"  mean achieved service level          : {df['service_level'].mean():.4f} "
          f"(target {config.SERVICE_LEVEL:.4f})")
    print(f"  series with >=1 stockout             : "
          f"{int((df['stockout_days'] > 0).sum()):,} of {len(df):,}")
    print(f"  series with >=1 replenishment        : "
          f"{int((df['arrivals'] > 0).sum()):,} of {len(df):,}")


if __name__ == "__main__":
    main()