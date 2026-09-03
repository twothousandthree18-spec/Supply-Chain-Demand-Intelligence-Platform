"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Scenario Engine: pure scenario calculations.

Step 3 deliverable. Every function is PURE and DETERMINISTIC (no I/O, no
globals, no randomness): identical inputs always produce identical outputs, so
scenario runs are repeatable from the same parameters.

The calculators CONSUME completed-phase outputs (SizingMoments from
fact_demand_analysis, forecast vectors from fact_forecast) and REUSE the
existing inventory policy/engine (src.inventory.simulation.policy_from_aggregates
and simulate_series) - forecasting/inventory logic is never re-implemented here.

Supported scenarios:
  1 demand_shock                  - unplanned demand uplift/drop; baseline policy
  2 lead_time_change              - re-derive safety stock / reorder point via
                                    the existing policy logic; re-run engine
  3 service_level_change          - re-size safety stock / reorder point
  4 reorder_policy                - alternative (s,Q) sizing vs baseline
  5 stockout_risk_prioritization  - rank series by projected stockout risk
  6 excess_inventory_prioritization - rank series by excess / positioning risk
  7 action_tradeoff               - structured scenario-vs-baseline comparison

Every output carries data_provenance='simulated'.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import replace
from typing import Optional, Sequence

import numpy as np

from src.inventory import config as inv_config
from src.inventory.simulation import (
    InventoryPolicy,
    policy_from_aggregates,
    simulate_series,
)

from . import config
from .contract import (
    ActionTradeoff,
    ScenarioDefinition,
    ScenarioError,
    ScenarioSeriesResult,
    SizingMoments,
)
from .validation import validate_scenario_definition


# --------------------------------------------------------------------------- #
# Demand / policy transforms (existing policy logic reused via
# policy_from_aggregates - NEVER re-implemented)
# --------------------------------------------------------------------------- #
def apply_demand_shock(forecast: Sequence[float], pct: float) -> np.ndarray:
    """Scale forecast demand by (1 + pct), clamped to >= 0.

    A demand shock is UNPLANNED here: the daily demand changes while the
    policy (safety stock / reorder point) stays at the baseline assumption
    set, revealing the true stress on the committed plan.
    """
    mult = 1.0 + float(pct)
    arr = np.asarray(forecast, dtype=np.float64) * mult
    return np.maximum(arr, 0.0)


def build_policy(
    moments: SizingMoments,
    *,
    lead_time_days: float = config.BASE_LEAD_TIME_DAYS,
    service_level: float = config.BASE_SERVICE_LEVEL,
    reorder_qty_multiple: float = config.BASE_REORDER_QTY_MULTIPLE,
    max_order_qty_coverage_days: float = config.BASE_MAX_ORDER_QTY_COVERAGE_DAYS,
) -> InventoryPolicy:
    """Size a policy via the existing Phase 3E logic from Phase 3C moments.

    All sizing math (safety stock = z x sigma x sqrt(LT), reorder point =
    lead-time demand + safety stock, (s,Q) capped by coverage) is delegated to
    src.inventory.simulation.policy_from_aggregates - identical to Phase 3E.
    """
    return policy_from_aggregates(
        float(moments.mean_daily_units),
        float(moments.std_daily_units),
        service_level=service_level,
        lead_time_days=float(lead_time_days),
        starting_coverage_days=config.STARTING_COVERAGE_DAYS,
        reorder_qty_multiple=float(reorder_qty_multiple),
        max_order_qty_coverage_days=float(max_order_qty_coverage_days),
        excess_coverage_days=config.EXCESS_COVERAGE_DAYS,
    )


# --------------------------------------------------------------------------- #
# Per-series simulation + summary (reuses the Phase 3E engine)
# --------------------------------------------------------------------------- #
def _replay_state(records, lead: int):
    """Shadow replay of the daily state machine from emitted records.

    Independent reconstruction of arrivals, final on-order, and final
    backorder from the produced records (arrival scheduling uses `lead` days,
    matching the Phase 3E driver's validate_trace).
    """
    on_hand = float(records[0].starting_inventory)
    on_order = 0.0
    backorder = 0.0
    pending = deque()
    arrivals = 0.0
    for rec in records:
        while pending and pending[0][0] == rec.day_id:
            _, qty = pending.popleft()
            on_hand += qty
            on_order -= qty
            arrivals += qty
        total = float(rec.demand_forecast) + backorder
        fulfilled = min(on_hand, total)
        unmet = total - fulfilled
        on_hand -= fulfilled
        backorder = unmet
        if rec.orders_placed > 0:
            on_order += float(rec.reorder_qty)
            pending.append((rec.day_id + lead, float(rec.reorder_qty)))
    return arrivals, on_order, backorder


def summarize(
    moments: SizingMoments, policy: InventoryPolicy, result
) -> dict:
    """Derive the per-series metric bundle from a simulated trace.

    Keys mirror the fact_scenario_result columns (plus first_stockout_offset,
    used for urgency scoring). All values are deterministic rounded numerics.
    """
    days = list(result.days)
    n = len(days)
    if n == 0:
        raise ScenarioError("cannot summarize an empty simulation")

    lead = int(round(policy.lead_time_days))
    arrivals, final_on_order, final_backorder = _replay_state(days, lead)

    cv = moments.cv
    try:
        cv = float(cv) if cv is not None else 0.0
    except (TypeError, ValueError):
        cv = 0.0
    cv = 0.0 if not math.isfinite(cv) else cv

    stockout_days = result.stockout_days
    excess_days = sum(1 for r in days if r.excess_inventory > 0)
    first_so = next((i for i, r in enumerate(days) if r.projected_stockout), None)

    return {
        # sizing / policy snapshot (mirrors the assumption set used)
        "expected_daily_demand": round(policy.expected_daily_demand, 4),
        "daily_sigma": round(float(moments.std_daily_units), 4),
        "cv": round(cv, 4),
        "total_units_hist": round(float(moments.total_units), 2),
        "safety_stock": round(float(policy.safety_stock), 4),
        "reorder_point": round(float(policy.reorder_point), 4),
        "reorder_qty": round(float(policy.reorder_quantity), 4),
        "starting_inventory": round(float(policy.starting_inventory), 4),
        "lead_time_days": round(float(policy.lead_time_days), 2),
        "service_level_target": round(float(policy.service_level), 6),
        # demand
        "total_demand": round(result.total_demand, 4),
        # service / stockout
        "stockout_days": int(stockout_days),
        "stockout_units": round(sum(r.stockout_units for r in days), 4),
        "service_level_achieved": round(result.service_level, 6),
        "fill_rate": round(result.fill_rate, 6),
        # reorder activity
        "reorder_frequency": int(result.total_orders_placed),
        "total_reorder_units": round(result.total_reorder_units, 4),
        "replenishment_units": round(arrivals, 4),
        # inventory
        "avg_inventory_position": round(sum(r.inventory_position for r in days) / n, 4),
        "avg_on_hand": round(sum(r.on_hand for r in days) / n, 4),
        "final_on_hand": round(result.final_on_hand, 4),
        "final_on_order": round(final_on_order, 4),
        "final_backorder": round(final_backorder, 4),
        # excess
        "excess_days": int(excess_days),
        "total_excess_units": round(sum(r.excess_inventory for r in days), 4),
        "avg_days_of_inventory": round(sum(r.days_of_inventory for r in days) / n, 4),
        # urgency helper
        "first_stockout_offset": first_so,
        "data_provenance": config.DATA_PROVENANCE_SIMULATED,
    }


def compute_deltas(baseline: dict, scenario: dict) -> dict:
    """Delta bundle (scenario - baseline) for all comparable metrics."""
    keys = (
        "stockout_days", "stockout_units", "service_level_achieved",
        "fill_rate", "reorder_frequency", "total_reorder_units",
        "avg_inventory_position", "excess_days", "total_excess_units",
        "avg_days_of_inventory",
    )
    return {
        f"delta_{k}": round(float(scenario[k]) - float(baseline[k]), 6)
        for k in keys
    }


def run_baseline(series) -> ScenarioSeriesResult:
    """Baseline reference result: exact Phase 3E reproduction for `series`.

    Consumes the same bounded inputs (moments + final forecasts) through the
    same engine, so it is byte-identical to the Phase 3E output without ever
    re-scanning the simulated fact table. Used as the delta baseline.
    """
    policy = build_policy(series.moments)
    result = simulate_series(series.forecast, policy=policy,
                             start_day=config.HORIZON_START_DAY)
    metrics = summarize(series.moments, policy, result)
    return ScenarioSeriesResult(
        product_surr_id=series.product_surr_id,
        store_surr_id=series.store_surr_id,
        scenario=None,
        policy=policy,
        metrics=metrics,
        deltas=None,
        data_provenance=config.DATA_PROVENANCE_SIMULATED,
    )


def run_scenario(
    series,
    definition: ScenarioDefinition,
    *,
    baseline_result: Optional[ScenarioSeriesResult] = None,
) -> ScenarioSeriesResult:
    """Run one per-series simulation scenario against `series`.

    Validates the definition, applies the scenario's demand/policy transform
    through the existing engine, summarizes, and (when a baseline result is
    supplied) attaches the delta bundle. Deterministic by construction.
    """
    validate_scenario_definition(definition)
    t = definition.scenario_type
    if t not in config.SIMULATION_SCENARIOS:
        raise ScenarioError(
            f"{t} is not a per-series simulation scenario; use score_and_rank "
            f"or compute_tradeoff for ranking/comparison scenarios")

    moments = series.moments

    if t == config.DEMAND_SHOCK:
        pct = float(definition.param("demand_adjustment_pct"))
        demand = apply_demand_shock(series.forecast, pct)
        # UNPLANNED shock: sizing stays at the baseline assumption set.
        policy = baseline_result.policy if baseline_result is not None \
            else build_policy(moments)

    elif t == config.LEAD_TIME_CHANGE:
        delta = float(definition.param("lead_time_delta_days"))
        new_lt = round(config.BASE_LEAD_TIME_DAYS + delta, 2)
        policy = build_policy(moments, lead_time_days=new_lt)
        demand = np.asarray(series.forecast, dtype=np.float64)

    elif t == config.SERVICE_LEVEL_CHANGE:
        target = float(definition.param("service_level_target"))
        policy = build_policy(moments, service_level=target)
        demand = np.asarray(series.forecast, dtype=np.float64)

    elif t == config.REORDER_POLICY:
        multiple = float(definition.param("reorder_qty_multiple"))
        cap = float(definition.param("max_order_qty_coverage_days"))
        policy = build_policy(moments, reorder_qty_multiple=multiple,
                              max_order_qty_coverage_days=cap)
        demand = np.asarray(series.forecast, dtype=np.float64)

    result = simulate_series(demand, policy=policy,
                             start_day=config.HORIZON_START_DAY)
    metrics = summarize(moments, policy, result)
    deltas = compute_deltas(baseline_result.metrics, metrics) \
        if baseline_result is not None else None

    return ScenarioSeriesResult(
        product_surr_id=series.product_surr_id,
        store_surr_id=series.store_surr_id,
        scenario=definition,
        policy=policy,
        metrics=metrics,
        deltas=deltas,
        data_provenance=config.DATA_PROVENANCE_SIMULATED,
    )


# --------------------------------------------------------------------------- #
# Ranking logic (scenarios 5 & 6) - deterministic percentile-rank scoring
# --------------------------------------------------------------------------- #
def percentile_ranks(values: Sequence[float]) -> list:
    """Empirical percentile ranks in [0,1] (rank/n, ties share the average).

    Deterministic and bounded; used to normalize volume/volatility so the risk
    scores are always comparable across arbitrary M5 scales.
    """
    vals = [float(v) if v is not None and not math.isnan(float(v)) else 0.0
            for v in values]
    n = len(vals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: (vals[i], i))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0           # average rank: 1..n
        for k in range(i, j + 1):
            out[order[k]] = (avg_rank - 1.0) / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def tier_for(score: float, tiers=None) -> str:
    """Map a risk score (0..1) to a tier via descending thresholds."""
    tiers = tiers or config.RISK_TIERS
    for threshold, label in tiers:
        if score >= threshold:
            return label
    return tiers[-1][1]


def _stockout_components(metrics: dict, volume_rank: float,
                         volatility_rank: float) -> dict:
    horizon = config.HORIZON_DAYS
    stockout_prob = metrics["stockout_days"] / horizon
    service_gap = max(
        0.0, metrics["service_level_target"] - metrics["service_level_achieved"])
    fo = metrics.get("first_stockout_offset")
    urgency = (1.0 - fo / horizon) if fo is not None else 0.0
    return {
        "volume_rank": round(volume_rank, 6),
        "volatility_rank": round(volatility_rank, 6),
        "stockout_prob": round(stockout_prob, 6),
        "service_gap": round(service_gap, 6),
        "urgency": round(urgency, 6),
    }


def _excess_components(metrics: dict, volume_rank: float) -> dict:
    horizon = config.HORIZON_DAYS
    ceiling = config.EXCESS_COVERAGE_DAYS
    excess_days_ratio = metrics["excess_days"] / horizon
    positioning_gap = max(
        0.0, (metrics["avg_days_of_inventory"] - ceiling) / ceiling)
    positioning_gap = min(1.0, positioning_gap)
    denom = max(metrics["total_demand"], 1e-9)
    excess_unit_efficiency = min(1.0, metrics["total_excess_units"] / denom)
    # High demand with near-target coverage is justified; a large positioning
    # gap signals inefficient inventory positioning regardless of volume.
    demand_justified = bool(volume_rank >= 0.5 and positioning_gap < 0.05)
    return {
        "excess_days_ratio": round(excess_days_ratio, 6),
        "positioning_gap": round(positioning_gap, 6),
        "excess_unit_efficiency": round(excess_unit_efficiency, 6),
        "volume_rank": round(volume_rank, 6),
        "demand_justified": demand_justified,
    }


def score_and_rank(
    results: Sequence[ScenarioSeriesResult],
    scenario_type: str,
    *,
    weights: Optional[dict] = None,
    tiers=None,
) -> list:
    """Score, tier, and rank a result population for a ranking scenario.

    Components are documented in src/scenario/config.py. Weights are
    normalized to sum to 1 (deterministic). Rank 1 = highest priority;
    ties broken by (product_surr_id, store_surr_id) for full determinism.
    """
    if scenario_type not in config.RANKING_SCENARIOS:
        raise ScenarioError(f"{scenario_type} is not a ranking scenario")
    population = list(results)
    if not population:
        return []

    if scenario_type == config.STOCKOUT_RISK:
        default_w = config.STOCKOUT_RISK_WEIGHTS
        component_keys = tuple(default_w)
        # weight keys are human-readable; component keys are the score inputs
        component_lookup = {
            "volume": "volume_rank",
            "volatility": "volatility_rank",
            "stockout_prob": "stockout_prob",
            "service_gap": "service_gap",
            "urgency": "urgency",
        }
    else:
        default_w = config.EXCESS_RISK_WEIGHTS
        component_keys = tuple(default_w)
        component_lookup = {k: k for k in component_keys}

    w = dict(default_w)
    w.update(weights or {})
    if not component_keys or any(k not in component_keys for k in w) or \
            sum(w.values()) <= 0:
        raise ScenarioError(f"invalid {scenario_type} weights")
    w_total = float(sum(w.values()))
    w = {k: v / w_total for k, v in w.items()}

    volume = [float(r.metrics["total_units_hist"]) for r in population]
    volume_ranks = percentile_ranks(volume)

    decorated = []
    if scenario_type == config.STOCKOUT_RISK:
        cv = [float(r.metrics.get("cv") or 0.0) for r in population]
        cv_ranks = percentile_ranks(cv)
        for r, vol_r, cv_r in zip(population, volume_ranks, cv_ranks):
            comps = _stockout_components(r.metrics, vol_r, cv_r)
            score = sum(w[k] * comps[component_lookup[k]] for k in component_keys)
            score = max(0.0, min(1.0, score))
            tier = tier_for(score, tiers)
            decorated.append((score, comps, tier, r))
    else:
        for r, vol_r in zip(population, volume_ranks):
            comps = _excess_components(r.metrics, vol_r)
            score = sum(w[k] * comps[k] for k in component_keys)
            score = max(0.0, min(1.0, score))
            tier = tier_for(score, tiers)
            decorated.append((score, comps, tier, r))

    # deterministic order: score desc, then entity ids asc
    decorated.sort(key=lambda pair: (
        -pair[0], pair[3].product_surr_id, pair[3].store_surr_id))

    ranked = []
    for rank, (score, comps, tier, r) in enumerate(decorated, start=1):
        ranked.append(replace(
            r,
            risk_score=round(score, 6),
            risk_tier=tier,
            risk_rank=int(rank),
            components=comps,
        ))
    return ranked


# --------------------------------------------------------------------------- #
# Comparison (scenario 7 - action trade-off)
# --------------------------------------------------------------------------- #
def aggregate_population(results: Sequence[ScenarioSeriesResult]) -> dict:
    """Population aggregates over a result set (deterministic)."""
    r = list(results)
    n = len(r)
    zeros = {
        "avg_inventory_position": 0.0,
        "avg_on_hand": 0.0,
        "total_reorder_units": 0.0,
        "total_reorder_frequency": 0,
        "mean_service_level": 0.0,
        "series_below_target": 0,
        "total_stockout_days": 0,
        "total_stockout_units": 0.0,
        "series_with_stockout": 0,
        "total_excess_days": 0,
        "total_excess_units": 0.0,
        "series_with_excess": 0,
        "mean_avg_days_of_inventory": 0.0,
        "n_series": n,
    }
    if n == 0:
        return zeros
    m_all = [x.metrics for x in r]
    out = {
        "n_series": n,
        "avg_inventory_position": round(
            sum(m["avg_inventory_position"] for m in m_all) / n, 4),
        "avg_on_hand": round(sum(m["avg_on_hand"] for m in m_all) / n, 4),
        "total_reorder_units": round(
            sum(m["total_reorder_units"] for m in m_all), 4),
        "total_reorder_frequency": int(
            sum(m["reorder_frequency"] for m in m_all)),
        "mean_service_level": round(
            sum(m["service_level_achieved"] for m in m_all) / n, 6),
        "series_below_target": int(
            sum(1 for m in m_all if m["service_level_achieved"]
                < m["service_level_target"])),
        "total_stockout_days": int(sum(m["stockout_days"] for m in m_all)),
        "total_stockout_units": round(
            sum(m["stockout_units"] for m in m_all), 4),
        "series_with_stockout": int(
            sum(1 for m in m_all if m["stockout_days"] > 0)),
        "total_excess_days": int(sum(m["excess_days"] for m in m_all)),
        "total_excess_units": round(
            sum(m["total_excess_units"] for m in m_all), 4),
        "series_with_excess": int(
            sum(1 for m in m_all if m["total_excess_units"] > 0)),
        "mean_avg_days_of_inventory": round(
            sum(m["avg_days_of_inventory"] for m in m_all) / n, 4),
    }
    return out


def _tradeoff_monetary(params: dict, baseline: dict, scenario: dict):
    """Monetary exposure ONLY from explicit cost assumptions; else None."""
    holding = params.get("unit_holding_cost")
    penalty = params.get("stockout_penalty_per_unit")
    if holding is None and penalty is None:
        return None
    out = {}
    if holding is not None:
        period = float(params.get("holding_period_days", config.HORIZON_DAYS))
        h = float(holding)
        out["unit_holding_cost_per_day"] = h
        out["holding_period_days"] = period
        out["baseline_holding_cost_exposure"] = round(
            h * baseline["avg_inventory_position"] * period, 6)
        out["scenario_holding_cost_exposure"] = round(
            h * scenario["avg_inventory_position"] * period, 6)
        out["delta_holding_cost_exposure"] = round(
            h * (scenario["avg_inventory_position"]
                 - baseline["avg_inventory_position"]) * period, 6)
    if penalty is not None:
        p = float(penalty)
        out["stockout_penalty_per_unit"] = p
        out["baseline_stockout_cost"] = round(p * baseline["total_stockout_units"], 6)
        out["scenario_stockout_cost"] = round(p * scenario["total_stockout_units"], 6)
        out["delta_stockout_cost"] = round(
            p * (scenario["total_stockout_units"]
                 - baseline["total_stockout_units"]), 6)
    return out


def compute_tradeoff(
    baseline_results: Sequence[ScenarioSeriesResult],
    scenario_results: Sequence[ScenarioSeriesResult],
    definition: ScenarioDefinition,
    *,
    baseline_scenario_name: str = "baseline",
) -> ActionTradeoff:
    """Structured comparison of scenario vs baseline (scenario 7).

    Produces cost/inventory exposure, service-level effect, stockout impact,
    and excess-inventory impact using OPERATIONAL metrics; monetary figures are
    only present when the scenario params supply an explicit cost assumption.
    """
    validate_scenario_definition(definition)
    if definition.scenario_type != config.ACTION_TRADEOFF:
        raise ScenarioError(
            f"compute_tradeoff requires scenario_type '{config.ACTION_TRADEOFF}', "
            f"got '{definition.scenario_type}'")

    b = aggregate_population(baseline_results)
    s = aggregate_population(scenario_results)

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
        f"comparison: '{definition.scenario_name}' vs baseline "
        f"'{baseline_scenario_name}'",
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
        baseline_scenario=str(definition.param(
            "baseline_scenario", baseline_scenario_name)),
        n_series=s["n_series"],
        inventory_exposure=inventory_exposure,
        service_level_effect=service_level_effect,
        stockout_impact=stockout_impact,
        excess_impact=excess_impact,
        assumptions=assumptions,
        monetary=_tradeoff_monetary(dict(definition.params), b, s),
        data_provenance=config.DATA_PROVENANCE_SIMULATED,
    )