"""
Phase 4 - Pure scenario calculation tests (steps 1-3 scope).

Requirement coverage:
  * demand-shock calculations
  * lead-time calculations (safety stock / reorder point reuse)
  * service-level calculations
  * reorder-policy comparisons
  * deterministic reproducibility
  * provenance / no modification of completed phases (pure, DB-free)
"""

import math

import numpy as np
import pytest

from src.inventory import config as inv_config
from src.inventory.simulation import policy_from_aggregates, simulate_series
from src.scenario import config
from src.scenario.contract import (
    ScenarioDefinition,
    ScenarioError,
    ScenarioSeriesResult,
)
from src.scenario.scenarios import (
    apply_demand_shock,
    build_policy,
    run_baseline,
    run_scenario,
    summarize,
)

from _helpers import make_series  # noqa: E402


def _defn(scenario_type, params, name="s", **kw):
    return ScenarioDefinition(scenario_name=name, scenario_type=scenario_type,
                              params=params, **kw)


# --------------------------------------------------------------------------- #
# Policy reuse: sizing must equal Phase 3E's policy_from_aggregates
# --------------------------------------------------------------------------- #
def test_build_policy_matches_phase3e_sizing():
    series = make_series(mean=10.0, std=4.0)
    p = build_policy(series.moments)
    ref = policy_from_aggregates(10.0, 4.0)
    assert p == ref
    assert p.safety_stock == pytest.approx(
        inv_config.SERVICE_LEVEL_Z * 4.0 * math.sqrt(7.0), abs=1e-6)
    assert p.reorder_point == pytest.approx(
        round(10.0 * 7.0 + p.safety_stock, 6))
    assert p.reorder_quantity == pytest.approx(70.0)


# --------------------------------------------------------------------------- #
# Demand shock
# --------------------------------------------------------------------------- #
def test_demand_shock_scales_and_clamps():
    fc = [10.0] * 28
    plus = apply_demand_shock(fc, 0.10)
    assert np.all(plus == pytest.approx(11.0))
    minus = apply_demand_shock(fc, -0.50)
    assert np.all(minus == pytest.approx(5.0))
    # pct below -100% clamps to 0 (validated to never reach -1 exactly)
    clamped = apply_demand_shock(fc, -1.5)
    assert np.all(clamped == 0.0)


def test_demand_shock_keeps_baseline_policy():
    series = make_series()
    base = run_baseline(series)
    shock = run_scenario(
        series, _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.20}),
        baseline_result=base)
    # UNPLANNED shock: policy unchanged, demand scaled
    assert shock.policy == base.policy
    assert shock.metrics["total_demand"] == pytest.approx(
        base.metrics["total_demand"] * 1.20)
    assert shock.metrics["data_provenance"] == config.DATA_PROVENANCE_SIMULATED
    assert shock.deltas is not None


def test_demand_shock_increases_stress_on_spike():
    # forecast far above sizing mean => inventory is always stressed
    series = make_series(mean=10.0, std=4.0, forecast=[60.0] + [10.0] * 27)
    base = run_baseline(series)
    shock = run_scenario(
        series, _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.20}),
        baseline_result=base)
    assert shock.deltas["delta_stockout_units"] > 0.0
    assert shock.deltas["delta_stockout_days"] >= 0
    assert shock.metrics["stockout_units"] > base.metrics["stockout_units"]


def test_demand_shock_decrease_relieves_stress():
    series = make_series(mean=10.0, std=4.0, forecast=[60.0] + [10.0] * 27)
    base = run_baseline(series)
    down = run_scenario(
        series, _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": -0.50}),
        baseline_result=base)
    assert down.metrics["total_demand"] == pytest.approx(
        base.metrics["total_demand"] * 0.50)
    assert down.deltas["delta_stockout_units"] <= 0.0


# --------------------------------------------------------------------------- #
# Lead time change (reuses existing policy logic)
# --------------------------------------------------------------------------- #
def test_lead_time_change_resizes_safety_stock():
    series = make_series(mean=10.0, std=4.0)
    base = run_baseline(series)
    run = run_scenario(
        series, _defn(config.LEAD_TIME_CHANGE, {"lead_time_delta_days": 2.0}),
        baseline_result=base)
    p = run.policy
    assert p.lead_time_days == pytest.approx(9.0)
    # sigma(lead-time) scales by sqrt(LT): safety(9)/safety(7) == sqrt(9/7)
    assert p.safety_stock / base.policy.safety_stock == pytest.approx(
        math.sqrt(9.0 / 7.0))
    assert p.reorder_point == pytest.approx(round(10.0 * 9.0 + p.safety_stock, 6))
    assert p.safety_stock > base.policy.safety_stock


def test_lead_time_decrease_raises_arrival_earlier():
    series = make_series(mean=10.0, std=4.0,
                         forecast=[30.0] * 28)
    base = run_baseline(series)
    short = run_scenario(
        series, _defn(config.LEAD_TIME_CHANGE, {"lead_time_delta_days": -3.0}),
        baseline_result=base)
    assert short.policy.lead_time_days == pytest.approx(4.0)
    # shorter lead time with resized safety eats less of the burst
    assert short.metrics["stockout_units"] <= base.metrics["stockout_units"] + 1e-6
    assert short.deltas is not None


def test_longer_lead_time_increases_burst_exposure():
    series = make_series(mean=10.0, std=4.0, forecast=[30.0] * 28)
    base = run_baseline(series)
    longer = run_scenario(
        series, _defn(config.LEAD_TIME_CHANGE, {"lead_time_delta_days": 3.0}),
        baseline_result=base)
    assert longer.metrics["stockout_units"] >= base.metrics["stockout_units"] - 1e-6


# --------------------------------------------------------------------------- #
# Service level change
# --------------------------------------------------------------------------- #
def test_service_level_change_monotonic_safety():
    series = make_series(mean=10.0, std=4.0)
    low = run_scenario(series, _defn(config.SERVICE_LEVEL_CHANGE,
                                     {"service_level_target": 0.80}))
    high = run_scenario(series, _defn(config.SERVICE_LEVEL_CHANGE,
                                      {"service_level_target": 0.99}))
    assert low.policy.service_level == pytest.approx(0.80)
    assert high.policy.safety_stock > low.policy.safety_stock
    assert high.policy.reorder_point > low.policy.reorder_point
    assert high.policy.reorder_quantity == low.policy.reorder_quantity  # SL does not resize Q
    assert high.policy.starting_inventory == low.policy.starting_inventory


def test_service_level_change_target_consistent():
    series = make_series(mean=10.0, std=4.0)
    run = run_scenario(series, _defn(config.SERVICE_LEVEL_CHANGE,
                                     {"service_level_target": 0.98}))
    assert run.metrics["service_level_target"] == pytest.approx(0.98)
    assert 0.0 <= run.metrics["service_level_achieved"] <= 1.0


# --------------------------------------------------------------------------- #
# Reorder policy comparison
# --------------------------------------------------------------------------- #
def test_reorder_policy_alternative_resizes_q():
    series = make_series(mean=10.0, std=4.0)
    base = run_baseline(series)
    alt = run_scenario(
        series, _defn(config.REORDER_POLICY,
                      {"reorder_qty_multiple": 14.0,
                       "max_order_qty_coverage_days": 28.0}),
        baseline_result=base)
    assert alt.policy.reorder_quantity == pytest.approx(140.0)
    assert alt.policy.reorder_point == base.policy.reorder_point  # s unchanged
    assert alt.deltas is not None


def test_reorder_policy_frequency_inventory_implications():
    # smaller, more frequent orders vs large rare orders
    series = make_series(mean=10.0, std=4.0, forecast=[10.0] * 28)
    base = run_baseline(series)               # Q=70
    small = run_scenario(
        series, _defn(config.REORDER_POLICY,
                      {"reorder_qty_multiple": 3.0,
                       "max_order_qty_coverage_days": 28.0}),
        baseline_result=base)                 # Q=30
    assert small.metrics["reorder_frequency"] >= base.metrics["reorder_frequency"]
    assert small.metrics["avg_inventory_position"] < base.metrics["avg_inventory_position"] + 1e-6


# --------------------------------------------------------------------------- #
# Baseline reproducibility + deltas + determinism
# --------------------------------------------------------------------------- #
def test_baseline_result_metrics_contract():
    series = make_series(mean=10.0, std=4.0, total=12450.0)
    base = run_baseline(series)
    assert isinstance(base, ScenarioSeriesResult)
    assert base.scenario is None
    m = base.metrics
    assert m["data_provenance"] == config.DATA_PROVENANCE_SIMULATED
    assert m["total_units_hist"] == pytest.approx(12450.0, abs=0.5)
    assert m["stockout_days"] == 0          # constant demand == sizing mean
    assert m["service_level_achieved"] == pytest.approx(1.0)
    for key in ("safety_stock", "reorder_point", "reorder_qty",
                "starting_inventory", "lead_time_days", "total_demand",
                "stockout_units", "fill_rate", "reorder_frequency",
                "avg_inventory_position", "excess_days", "avg_days_of_inventory"):
        assert key in m


def test_deltas_key_definition():
    keys = ("delta_stockout_days", "delta_stockout_units",
            "delta_service_level_achieved", "delta_fill_rate",
            "delta_reorder_frequency", "delta_total_reorder_units",
            "delta_avg_inventory_position", "delta_excess_days",
            "delta_total_excess_units", "delta_avg_days_of_inventory")
    series = make_series(forecast=[60.0] + [10.0] * 27)
    base = run_baseline(series)
    run = run_scenario(series, _defn(config.DEMAND_SHOCK,
                                     {"demand_adjustment_pct": 0.15}),
                       baseline_result=base)
    assert set(run.deltas) == set(keys)
    assert run.deltas["delta_stockout_days"] == (
        run.metrics["stockout_days"] - base.metrics["stockout_days"])


def test_summarize_determinism():
    series = make_series(forecast=[55.0] + [9.0] * 27)
    policy = build_policy(series.moments)
    a = summarize(series.moments, policy,
                  simulate_series(series.forecast, policy=policy,
                                  start_day=config.HORIZON_START_DAY))
    b = summarize(series.moments, policy,
                  simulate_series(series.forecast, policy=policy,
                                  start_day=config.HORIZON_START_DAY))
    assert a == b


def test_run_scenario_deterministic():
    series = make_series(forecast=[30.0] * 28)
    base = run_baseline(series)
    d = _defn(config.LEAD_TIME_CHANGE, {"lead_time_delta_days": 2.0})
    r1 = run_scenario(series, d, baseline_result=base)
    r2 = run_scenario(series, d, baseline_result=base)
    assert r1.metrics == r2.metrics
    assert r1.deltas == r2.deltas
    assert r1.policy == r2.policy


def test_run_scenario_rejects_ranking_type_here():
    series = make_series()
    with pytest.raises(ScenarioError):
        run_scenario(series, _defn(config.STOCKOUT_RISK, {}))


def test_run_scenario_validates_definition():
    series = make_series()
    bad = _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 50.0})
    from src.scenario.contract import ScenarioValidationError
    with pytest.raises(ScenarioValidationError):
        run_scenario(series, bad)


def test_z_service_used_from_existing_logic():
    # scenario reuses the inventory z formula: check the 0.95 constant path
    from src.inventory.formulas import z_service
    assert z_service(0.95) == pytest.approx(inv_config.SERVICE_LEVEL_Z)