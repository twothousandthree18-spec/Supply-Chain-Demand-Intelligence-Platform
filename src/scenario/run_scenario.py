"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Production scenario driver (bounded, resumable).

Runs 7 configured scenarios against all 30,490 product/store series using the
pure scenario engine (src/scenario/scenarios.py). Every write is idempotent
(DELETE/UPSERT) and batched with periodic commits; interrupted runs are marked
failed on the next invocation.

Scenarios (execution order):
  1 baseline                - reference simulation (Phase 3E reproduction)
  2 demand_shock_p20        - +20% unplanned demand uplift
  3 lead_time_plus_2d       - lead time increased by 2 days
  4 service_level_99        - target cycle service level raised to 0.99
  5 reorder_policy_alt      - alternative (s,Q) sizing (14d multiple, 28d cap)
  6 stockout_risk_rank      - rank all series by projected stockout risk
  7 excess_risk_rank        - rank all series by excess inventory risk

Inputs (bounded, no 59M observed-fact scan):
  * fact_demand_analysis    (Phase 3C sizing moments)
  * fact_forecast is_final  (Phase 3D final forecasts, days [1942,1969])
  * assumption_set id=1     (Phase 3E baseline)

Outputs (all data_provenance='simulated'):
  * scenario                - scenario definitions (7 rows, idempotent upsert)
  * scenario_rules          - persisted thresholds/weights (21 rows, idempotent)
  * fact_scenario_run       - one row per execution (7 total)
  * fact_scenario_result    - per-series results (30,490 x 7 = 213,430 rows)
  * fact_scenario_comparison - aggregate tradeoff per non-baseline scenario (4 rows)

Run with --pilot-only to validate the full path on a subset without DB writes.
Run with --scenario NAME to execute a single scenario (for re-runs).

Driver pattern mirrors run_inventory_simulation.py and run_forecasting.py.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from src.etl.db_utils import connect
from src.scenario import config
from src.scenario.contract import (
    ActionTradeoff,
    ScenarioDefinition,
    ScenarioSeriesResult,
    SeriesInput,
    SizingMoments,
)
from src.scenario.scenarios import (
    aggregate_population,
    build_policy,
    run_baseline,
    run_scenario,
    score_and_rank,
    simulate_series,
)
from src.scenario.validation import validate_params

PIPELINE = "scenario_engine"

# --------------------------------------------------------------------------- #
# Scenario definitions (production run)
# --------------------------------------------------------------------------- #
SCENARIOS = [
    {"name": "baseline",            "type": "baseline",
     "params": {},                  "desc": "Reference baseline (Phase 3E reproduction)"},
    {"name": "demand_shock_p20",    "type": "demand_shock",
     "params": {"demand_adjustment_pct": 0.20},
     "desc": "+20% unplanned demand uplift; baseline policy unchanged"},
    {"name": "lead_time_plus_2d",   "type": "lead_time_change",
     "params": {"lead_time_delta_days": 2.0},
     "desc": "Lead time increased by 2 days (7 -> 9); policy re-sized"},
    {"name": "service_level_99",    "type": "service_level_change",
     "params": {"service_level_target": 0.99},
     "desc": "Target cycle service level raised to 0.99; safety stock re-sized"},
    {"name": "reorder_policy_alt",  "type": "reorder_policy",
     "params": {"reorder_qty_multiple": 14.0,
                "max_order_qty_coverage_days": 28.0},
     "desc": "Alternative (s,Q): 14-day reorder multiple, 28-day coverage cap"},
    {"name": "stockout_risk_rank",  "type": "stockout_risk_prioritization",
     "params": {},                  "desc": "Rank all series by projected stockout risk"},
    {"name": "excess_risk_rank",    "type": "excess_inventory_prioritization",
     "params": {},                  "desc": "Rank all series by excess inventory risk"},
]

# --------------------------------------------------------------------------- #
# Small helpers
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


# --------------------------------------------------------------------------- #
# Bounded pulls (never scan the 59M observed-fact table)
# --------------------------------------------------------------------------- #
def _stage_pairs(conn, pairs):
    """Materialize target (product, store) pairs into a session temp table.

    A naive approach inlines every pair into a single
    `WHERE (product_sr_id, store_sr_id) IN ((...),(...),...)` literal.
    With ~30k series that parse tree exceeds PostgreSQL max_stack_depth and
    fails with StatementTooComplex. Funnelling the pairs through a small temp
    table keeps the prepared SQL small and lets the planner use the existing
    fact indexes. Returns True when a pair filter should be applied.
    """
    if pairs is None:
        return False
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _stage_pairs")
        cur.execute(
            "CREATE TEMP TABLE _stage_pairs "
            "(product_surr_id bigint, store_surr_id bigint) "
            "ON COMMIT PRESERVE ROWS")
        cur.executemany(
            "INSERT INTO _stage_pairs (product_surr_id, store_surr_id) "
            "VALUES (%s, %s)",
            [(int(a), int(b)) for a, b in pairs])
    return True


def _pairs_predicate(alias):
    """EXISTS predicate against the staged pair temp table."""
    return (
        f" AND EXISTS (SELECT 1 FROM _stage_pairs sp "
        f"WHERE sp.product_surr_id = {alias}.product_surr_id "
        f"AND sp.store_surr_id = {alias}.store_surr_id)")


def pull_sizing(conn, pairs=None):
    """Per-series demand moments from fact_demand_analysis."""
    where = "WHERE analysis_window='observed_full'"
    if _stage_pairs(conn, pairs):
        where += _pairs_predicate("da")
    df = fetch(conn, f"""
        SELECT da.product_surr_id, da.store_surr_id, da.total_units,
               da.mean_daily_units, da.std_daily_units
        FROM fact_demand_analysis da
        {where}
    """)
    for col in ("total_units", "mean_daily_units", "std_daily_units"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def pull_forecasts(conn, pairs=None):
    """Final Phase 3D forecasts for days [1942,1969]."""
    where = (
        f"WHERE is_final=TRUE AND forecast_date BETWEEN {config.HORIZON_START_DAY} "
        f"AND {config.HORIZON_END_DAY}"
    )
    if _stage_pairs(conn, pairs):
        where += _pairs_predicate("f")
    df = fetch(conn, f"""
        SELECT f.product_surr_id, f.store_surr_id, f.forecast_date,
               f.forecast_value
        FROM fact_forecast f
        {where}
        ORDER BY f.product_surr_id, f.store_surr_id, f.forecast_date
    """)
    df["forecast_value"] = pd.to_numeric(df["forecast_value"], errors="coerce")
    return df


def forecast_array(g):
    """Ordered 28-day forecast vector for one (product, store) group."""
    g = g.sort_values("forecast_date")
    arr = g["forecast_value"].to_numpy(dtype=np.float64)
    if np.any(np.isnan(arr)):
        arr = np.nan_to_num(arr, nan=0.0)
    if arr.shape[0] != config.HORIZON_DAYS:
        raise ValueError(
            f"expected {config.HORIZON_DAYS} forecast days, got {arr.shape[0]}")
    return arr


def build_inventory_policy(mean_daily, std_daily):
    """InventoryPolicy from Phase 3C demand moments."""
    mean = float(mean_daily) if not pd.isna(mean_daily) else 0.0
    std = float(std_daily) if not pd.isna(std_daily) else 0.0
    return build_policy(
        SizingMoments(
            mean_daily_units=mean, std_daily_units=std,
            total_units=0.0, cv=(std / mean if mean > 0 else 0.0)))


# --------------------------------------------------------------------------- #
# Simulation orchestration
# --------------------------------------------------------------------------- #
def simulate_all(sizing, fcast_by_key, on_series=None):
    """Run the engine over every series; optional streaming callback."""
    metrics = []
    for _, r in sizing.iterrows():
        pid, sid = int(r["product_surr_id"]), int(r["store_surr_id"])
        g = fcast_by_key.get((pid, sid))
        if g is None:
            raise ValueError(f"({pid},{sid}): no final forecast rows found")
        policy = build_inventory_policy(r["mean_daily_units"], r["std_daily_units"])
        fc = forecast_array(g)
        result = simulate_series(fc, policy=policy,
                                 start_day=config.HORIZON_START_DAY)
        m = _validate_trace(pid, sid, policy, result.days)
        metrics.append(m)
        if on_series is not None:
            on_series(pid, sid, result)
    return metrics


def _validate_trace(pid, sid, policy, days):
    """Validate the simulation trace and return per-series metrics."""
    n = len(days)
    if n == 0:
        raise AssertionError(f"({pid},{sid}): empty simulation trace")
    stockout_days = 0
    total_stockout_units = 0.0
    excess_days = 0
    for r in days:
        if r.stockout_units > 0 and not r.projected_stockout:
            raise AssertionError(
                f"({pid},{sid}) day {r.day_id}: stockout_units>0 "
                "but projected_stockout=False")
        if r.stockout_units <= 0 and r.projected_stockout:
            raise AssertionError(
                f"({pid},{sid}) day {r.day_id}: projected_stockout=True "
                "but stockout_units<=0")
        if r.data_provenance != config.DATA_PROVENANCE_SIMULATED:
            raise AssertionError(
                f"({pid},{sid}) day {r.day_id}: provenance "
                f"{r.data_provenance!r} != 'simulated'")
        if r.stockout_units > 0:
            stockout_days += 1
            total_stockout_units += r.stockout_units
        if r.excess_inventory > 0:
            excess_days += 1
    demand_total = sum(r.demand_forecast for r in days)
    fill_rate = (1.0 - total_stockout_units / demand_total
                 if demand_total > 0 else 1.0)
    return {
        "product_surr_id": pid, "store_surr_id": sid,
        "expected_daily_demand": policy.expected_daily_demand,
        "safety_stock": policy.safety_stock,
        "reorder_point": policy.reorder_point,
        "reorder_quantity": policy.reorder_quantity,
        "starting_inventory": policy.starting_inventory,
        "order_days": sum(1 for r in days if r.orders_placed > 0),
        "arrivals": round(sum(r.reorder_qty for r in days
                              if r.reorder_qty > 0), 4),
        "stockout_days": stockout_days,
        "stockout_units": round(total_stockout_units, 4),
        "excess_days": excess_days,
        "fill_rate": round(fill_rate, 6),
        "service_level": round(1.0 - stockout_days / n, 6),
    }


# --------------------------------------------------------------------------- #
# Scenario computation (pure layer bridge)
# --------------------------------------------------------------------------- #
def compute_scenario(name, stype, params, sizing, fcast_by_key,
                     baseline_results=None):
    """Run one scenario across all series; return list[ScenarioSeriesResult]."""
    defn = ScenarioDefinition(
        scenario_name=name, scenario_type=stype,
        params=params, description="")
    results = []
    for _, r in sizing.iterrows():
        pid, sid = int(r["product_surr_id"]), int(r["store_surr_id"])
        g = fcast_by_key.get((pid, sid))
        if g is None:
            raise ValueError(f"({pid},{sid}): no final forecast rows found")
        moments = SizingMoments(
            mean_daily_units=float(r["mean_daily_units"]),
            std_daily_units=float(r["std_daily_units"]),
            total_units=float(r["total_units"]),
            cv=(float(r["std_daily_units"]) / float(r["mean_daily_units"])
                if float(r["mean_daily_units"]) > 0 else 0.0))
        series = SeriesInput(pid, sid, moments, forecast_array(g))
        if stype == "baseline":
            result = run_baseline(series)
        else:
            base = baseline_results.get((pid, sid))
            result = run_scenario(series, defn, baseline_result=base)
        results.append(result)
    return results


def compute_ranking(stype, baseline_results):
    """Score and rank the baseline population for a ranking scenario."""
    pop = list(baseline_results.values())
    return score_and_rank(pop, stype)


def _result_callback(name, stype, params, sizing, fcast_by_key,
                     baseline_results, on_result):
    """Run a scenario across all series; populate baseline_results dict."""
    results = compute_scenario(name, stype, params, sizing, fcast_by_key,
                               baseline_results=baseline_results
                               if stype != "baseline" else None)
    for r in results:
        if stype == "baseline":
            baseline_results[(r.product_surr_id, r.store_surr_id)] = r
        if on_result is not None:
            on_result(r)


# --------------------------------------------------------------------------- #
# Comparison aggregation (no re-simulation)
# --------------------------------------------------------------------------- #
class _M:
    """Lightweight metrics wrapper for aggregate_population."""
    def __init__(self, metrics):
        self.metrics = metrics


def compute_comparison(baseline_results, target_results, definition,
                       baseline_name="baseline"):
    """Structured scenario-vs-baseline comparison (scenario 7)."""
    b = aggregate_population([_M(r.metrics) for r in baseline_results.values()])
    s = aggregate_population([_M(r.metrics) for r in target_results.values()])

    def d(key, digits=6):
        return round(float(s[key]) - float(b[key]), digits)

    inventory_exposure = {
        "baseline_avg_inventory_position": b["avg_inventory_position"],
        "scenario_avg_inventory_position": s["avg_inventory_position"],
        "delta_avg_inventory_position": d("avg_inventory_position"),
        "baseline_total_reorder_units": b["total_reorder_units"],
        "scenario_total_reorder_units": s["total_reorder_units"],
        "delta_total_reorder_units": d("total_reorder_units"),
        "baseline_total_reorder_frequency": b["total_reorder_frequency"],
        "scenario_total_reorder_frequency": s["total_reorder_frequency"],
        "delta_reorder_frequency": d("total_reorder_frequency", 0),
    }
    service_level_effect = {
        "baseline_mean_service_level": b["mean_service_level"],
        "scenario_mean_service_level": s["mean_service_level"],
        "delta_mean_service_level": d("mean_service_level"),
        "baseline_series_below_target": b["series_below_target"],
        "scenario_series_below_target": s["series_below_target"],
        "delta_series_below_target": d("series_below_target", 0),
    }
    stockout_impact = {
        "baseline_total_stockout_days": b["total_stockout_days"],
        "scenario_total_stockout_days": s["total_stockout_days"],
        "delta_total_stockout_days": d("total_stockout_days", 0),
        "baseline_total_stockout_units": b["total_stockout_units"],
        "scenario_total_stockout_units": s["total_stockout_units"],
        "delta_total_stockout_units": d("total_stockout_units"),
        "baseline_series_with_stockout": b["series_with_stockout"],
        "scenario_series_with_stockout": s["series_with_stockout"],
    }
    excess_impact = {
        "baseline_total_excess_days": b["total_excess_days"],
        "scenario_total_excess_days": s["total_excess_days"],
        "delta_total_excess_days": d("total_excess_days", 0),
        "baseline_total_excess_units": b["total_excess_units"],
        "scenario_total_excess_units": s["total_excess_units"],
        "delta_total_excess_units": d("total_excess_units"),
        "baseline_series_with_excess": b["series_with_excess"],
        "scenario_series_with_excess": s["series_with_excess"],
    }

    assumptions = (
        "operational metrics only (units, days, stockouts, service level, "
        "order quantity); no financial savings are fabricated",
        f"comparison: '{definition.scenario_name}' vs baseline '{baseline_name}'",
        f"horizon [{config.HORIZON_START_DAY}, {config.HORIZON_END_DAY}] "
        f"({config.HORIZON_DAYS} days)",
        f"base assumption set id={definition.base_assumption_set_id}",
        "service level = cycle CSL = 1 - stockout_days / horizon",
        "inventory exposure measured in average inventory position / "
        "reorder units (units)",
    )

    return ActionTradeoff(
        scenario_name=definition.scenario_name,
        target_scenario=str(definition.param("target_scenario")),
        baseline_scenario=str(definition.param("baseline_scenario", baseline_name)),
        n_series=s["n_series"],
        inventory_exposure=inventory_exposure,
        service_level_effect=service_level_effect,
        stockout_impact=stockout_impact,
        excess_impact=excess_impact,
        assumptions=assumptions,
        monetary=None,
        data_provenance=config.DATA_PROVENANCE_SIMULATED,
    )


# --------------------------------------------------------------------------- #
# Persistence (idempotent, batched)
# --------------------------------------------------------------------------- #
def upsert_rules(conn):
    """Write scenario_rules from config.RULES (DELETE + INSERT, idempotent)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM scenario_rules")
        for key, (value, desc) in config.RULES.items():
            cur.execute(
                "INSERT INTO scenario_rules (rule_key, rule_value, description) "
                "VALUES (%s, %s, %s)", (key, value, desc))
    conn.commit()


def upsert_scenario(conn, name, stype, params, desc, assumption_set_id):
    """Upsert a scenario definition; return scenario_id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scenario "
            "(scenario_name, scenario_type, params_json, "
            " base_assumption_set_id, description, version) "
            "VALUES (%s,%s,%s,%s,%s,1) "
            "ON CONFLICT (scenario_name) DO UPDATE SET "
            "  scenario_type=EXCLUDED.scenario_type, "
            "  params_json=EXCLUDED.params_json, "
            "  base_assumption_set_id=EXCLUDED.base_assumption_set_id, "
            "  description=EXCLUDED.description "
            "RETURNING scenario_id",
            (name, stype, json.dumps(params), assumption_set_id, desc))
        scenario_id = cur.fetchone()[0]
    conn.commit()
    return int(scenario_id)


def start_run(conn):
    """Mark abandoned runs failed; start a new ETL run; return run_id."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_run_log SET status='failed', "
            "error_message='abandoned (no live process)' "
            "WHERE status='running' AND pipeline=%s", (PIPELINE,))
    with conn.cursor() as cur:
        cur.execute("SELECT start_etl_run(%s)", (PIPELINE,))
        run_id = cur.fetchone()[0]
    conn.commit()
    return int(run_id)


def finish_run(conn, run_id, status, records=0, error=None):
    """Finish an ETL run."""
    with conn.cursor() as cur:
        cur.execute("SELECT finish_etl_run(%s,%s,%s,%s,%s)",
                    (run_id, status, records, records, error))
    conn.commit()


def _result_to_row(run_id, result, scenario_def):
    """Convert a ScenarioSeriesResult to a fact_scenario_result row tuple."""
    m = result.metrics
    pol = result.policy
    sc = result.scenario
    sd = sc.params if sc else {}
    return (
        run_id,
        result.product_surr_id, result.store_surr_id,
        m.get("expected_daily_demand"), m.get("daily_sigma"),
        m.get("cv"), m.get("total_units_hist"),
        pol.safety_stock, pol.reorder_point, pol.reorder_quantity,
        pol.starting_inventory, pol.lead_time_days, pol.service_level,
        m.get("total_demand"),
        m.get("stockout_days"), m.get("stockout_units"),
        m.get("service_level_achieved"), m.get("fill_rate"),
        m.get("reorder_frequency"), m.get("total_reorder_units"),
        m.get("replenishment_units"),
        m.get("avg_inventory_position"), m.get("avg_on_hand"),
        m.get("final_on_hand"), m.get("final_on_order"),
        m.get("final_backorder"),
        m.get("excess_days"), m.get("total_excess_units"),
        m.get("avg_days_of_inventory"),
        getattr(result, "risk_score", None),
        getattr(result, "risk_tier", None),
        getattr(result, "risk_rank", None),
        json.dumps(getattr(result, "components", None))
        if getattr(result, "components", None) else None,
        result.deltas.get("delta_stockout_days") if result.deltas else None,
        result.deltas.get("delta_stockout_units") if result.deltas else None,
        result.deltas.get("delta_service_level_achieved") if result.deltas else None,
        result.deltas.get("delta_fill_rate") if result.deltas else None,
        result.deltas.get("delta_reorder_frequency") if result.deltas else None,
        result.deltas.get("delta_total_reorder_units") if result.deltas else None,
        result.deltas.get("delta_avg_inventory_position") if result.deltas else None,
        result.deltas.get("delta_excess_days") if result.deltas else None,
        result.deltas.get("delta_total_excess_units") if result.deltas else None,
        result.deltas.get("delta_avg_days_of_inventory") if result.deltas else None,
        config.DATA_PROVENANCE_SIMULATED,
    )


_SIM_INSERT = (
    "INSERT INTO fact_scenario_result "
    "(scenario_run_id, product_surr_id, store_surr_id,"
    " expected_daily_demand, daily_sigma, cv, total_units_hist,"
    " safety_stock, reorder_point, reorder_qty, starting_inventory,"
    " lead_time_days, service_level_target,"
    " total_demand, stockout_days, stockout_units,"
    " service_level_achieved, fill_rate,"
    " reorder_frequency, total_reorder_units, replenishment_units,"
    " avg_inventory_position, avg_on_hand,"
    " final_on_hand, final_on_order, final_backorder,"
    " excess_days, total_excess_units, avg_days_of_inventory,"
    " risk_score, risk_tier, risk_rank, risk_components,"
    " delta_stockout_days, delta_stockout_units, delta_service_level,"
    " delta_fill_rate, delta_reorder_frequency, delta_total_reorder_units,"
    " delta_avg_inventory_position, delta_excess_days,"
    " delta_total_excess_units, delta_avg_days_of_inventory,"
    " data_provenance) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


def batch_write_results(conn, run_id, results, scenario_def,
                        chunk=5000, commit_every=8):
    """Batched write of ScenarioSeriesResult list to fact_scenario_result."""
    cur = conn.cursor()
    buf = []
    total = 0
    try:
        for result in results:
            buf.append(_result_to_row(run_id, result, scenario_def))
            if len(buf) >= chunk:
                cur.executemany(_SIM_INSERT, buf)
                buf.clear()
                total += chunk
                if total % (chunk * commit_every) == 0:
                    conn.commit()
        if buf:
            cur.executemany(_SIM_INSERT, buf)
        conn.commit()
    finally:
        cur.close()


def persist_comparison(conn, run_id, comp):
    """Persist an ActionTradeoff as one fact_scenario_comparison row."""
    agg = {
        "inventory_exposure": comp.inventory_exposure,
        "service_level_effect": comp.service_level_effect,
        "stockout_impact": comp.stockout_impact,
        "excess_impact": comp.excess_impact,
        "assumptions": comp.assumptions,
        "monetary": comp.monetary,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO fact_scenario_comparison "
            "(scenario_run_id, baseline_scenario_run_id, aggregate_json, "
            " n_series, horizon_days, data_provenance) "
            "VALUES (%s, NULL, %s, %s, %s, %s) "
            "ON CONFLICT (scenario_run_id) DO UPDATE SET "
            "  aggregate_json=EXCLUDED.aggregate_json, "
            "  n_series=EXCLUDED.n_series, "
            "  horizon_days=EXCLUDED.horizon_days",
            (run_id, json.dumps(agg), comp.n_series,
             config.HORIZON_DAYS, config.DATA_PROVENANCE_SIMULATED))
    conn.commit()


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #
def effective_top_n(top_n, pilot_only):
    """Resolve the series limit: explicit --top-n wins; pilot-only defaults
    to 64; otherwise None, meaning production scope = ALL series."""
    if top_n is not None:
        return top_n
    return 64 if pilot_only else None


def build_parser():
    parser = argparse.ArgumentParser(description="Phase 4 scenario engine")
    parser.add_argument("--pilot-only", action="store_true",
                        help="validate on 64 series without DB writes")
    parser.add_argument("--top-n", type=int, default=None,
                        help="explicit bounded subset size for pilot runs "
                             "(default: ALL series in production)")
    parser.add_argument("--scenario", type=str, default=None,
                        help="run a single scenario by name")
    return parser


def main():
    args = build_parser().parse_args()

    conn = connect()
    conn.set_client_encoding("UTF8")
    run_id = None

    if not args.pilot_only:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE etl_run_log SET status='failed', "
                "error_message='abandoned (no live process)' "
                "WHERE status='running' AND pipeline=%s", (PIPELINE,))
        with conn.cursor() as cur:
            cur.execute("SELECT start_etl_run(%s)", (PIPELINE,))
            run_id = cur.fetchone()[0]
        conn.commit()

    print(f"[scenario_engine] run_id={run_id} pilot_only={args.pilot_only}")
    t0 = time.time()

    try:
        sizing = pull_sizing(conn)
        limit = effective_top_n(args.top_n, args.pilot_only)
        if limit is not None:
            sizing = (sizing.sort_values("total_units", ascending=False)
                          .head(limit).reset_index(drop=True))
        pairs = list(zip(sizing["product_surr_id"].astype(int),
                         sizing["store_surr_id"].astype(int)))
        sizing = sizing[sizing[["product_surr_id", "store_surr_id"]]
                        .apply(tuple, axis=1).isin(pairs)].reset_index(drop=True)
        print(f"  ... {len(sizing):,} series sized from fact_demand_analysis")

        fcast = pull_forecasts(conn, pairs=pairs)
        print(f"  ... {len(fcast):,} final forecast rows pulled")
        fcast_by_key = {k: g for k, g in fcast.groupby(
            ["product_surr_id", "store_surr_id"])}

        if args.pilot_only:
            metrics = simulate_all(sizing, fcast_by_key)
            print(f"  simulated {len(metrics):,} series (all traces validated)")
            print(f"[ok] pilot-only complete; no DB writes. "
                  f"elapsed={time.time()-t0:.1f}s")
            conn.close()
            return

        upsert_rules(conn)
        print("  ... scenario_rules persisted (idempotent)")

        assumption_set_id = config.BASE_ASSUMPTION_SET_ID
        scenario_ids = {}
        for s in SCENARIOS:
            sid = upsert_scenario(
                conn, s["name"], s["type"], s["params"], s["desc"],
                assumption_set_id)
            scenario_ids[s["name"]] = sid
        print(f"  ... {len(scenario_ids)} scenario definitions persisted")

        baseline_results = {}
        total_rows = 0
        scenarios_to_run = SCENARIOS
        if args.scenario:
            scenarios_to_run = [s for s in SCENARIOS if s["name"] == args.scenario]
            if not scenarios_to_run:
                raise ValueError(f"unknown scenario: {args.scenario!r}")

        for sc in scenarios_to_run:
            name, stype = sc["name"], sc["type"]
            params, desc = sc["params"], sc["desc"]
            print(f"\n  [{name}] type={stype} ...")

            if stype in config.RANKING_SCENARIOS:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fact_scenario_run "
                        "(scenario_id, assumption_set_id, status, "
                        " data_provenance) VALUES (%s,%s,'running','simulated') "
                        "RETURNING scenario_run_id",
                        (scenario_ids[name], assumption_set_id))
                    srun_id = cur.fetchone()[0]
                conn.commit()

                ranked = compute_ranking(stype, baseline_results)
                batch_write_results(conn, srun_id, ranked, None)
                total_rows += len(ranked)
                finish_run(conn, srun_id, "success", len(ranked))
                print(f"  {len(ranked):,} ranked rows written")
                continue

            if stype == "action_tradeoff":
                target_name = params.get("target_scenario", "demand_shock_p20")
                if target_name not in baseline_results:
                    raise ValueError(
                        f"target scenario {target_name!r} results not found; "
                        f"run it first")
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fact_scenario_run "
                        "(scenario_id, assumption_set_id, status, "
                        " data_provenance) VALUES (%s,%s,'running','simulated') "
                        "RETURNING scenario_run_id",
                        (scenario_ids[name], assumption_set_id))
                    srun_id = cur.fetchone()[0]
                conn.commit()

                defn = ScenarioDefinition(
                    scenario_name=name, scenario_type=stype,
                    params=params, description=desc)
                comp = compute_comparison(
                    baseline_results, baseline_results[target_name],
                    defn, baseline_name="baseline")
                persist_comparison(conn, srun_id, comp)
                finish_run(conn, srun_id, "success", 0)
                print(f"  comparison persisted (0 per-series rows)")
                continue

            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO fact_scenario_run "
                    "(scenario_id, assumption_set_id, status, "
                    " data_provenance) VALUES (%s,%s,'running','simulated') "
                    "RETURNING scenario_run_id",
                    (scenario_ids[name], assumption_set_id))
                srun_id = cur.fetchone()[0]
            conn.commit()

            defn = ScenarioDefinition(
                scenario_name=name, scenario_type=stype,
                params=params, description=desc)
            results = compute_scenario(
                name, stype, params, sizing, fcast_by_key,
                baseline_results=baseline_results if stype != "baseline" else None)
            batch_write_results(conn, srun_id, results, defn)
            total_rows += len(results)

            if stype == "baseline":
                for r in results:
                    baseline_results[(r.product_surr_id, r.store_surr_id)] = r
                print(f"  baseline stored ({len(results):,} series)")
            else:
                print(f"  {len(results):,} rows written")

            finish_run(conn, srun_id, "success", len(results))

        finish_run(conn, run_id, "success", total_rows)
        print(f"\n[ok] {total_rows:,} total rows in {time.time()-t0:.1f}s")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        if run_id is not None:
            try:
                finish_run(conn, run_id, "failed", error=str(e))
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
