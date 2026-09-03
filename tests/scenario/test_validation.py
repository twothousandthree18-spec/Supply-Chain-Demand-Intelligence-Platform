"""
Phase 4 - Scenario parameter validation tests (steps 1-3 scope).

Requirement coverage: scenario parameter validation, edge cases and invalid
parameter combinations, deterministic rejection, unknown types/keys.
"""

import math

import pytest

from src.scenario import config
from src.scenario.contract import (
    ScenarioDefinition,
    ScenarioValidationError,
)
from src.scenario.validation import validate_params, validate_scenario_definition


def _defn(scenario_type, params, name="t", **kw):
    return ScenarioDefinition(
        scenario_name=name, scenario_type=scenario_type, params=params, **kw)


def test_unknown_scenario_type_rejected():
    with pytest.raises(ScenarioValidationError):
        validate_params("teleport", {})


def test_demand_shock_requires_pct_and_bounds():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.DEMAND_SHOCK, {})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.DEMAND_SHOCK, {"demand_adjustment_pct": 12.0})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.DEMAND_SHOCK, {"demand_adjustment_pct": -1.0})
    with pytest.raises(ScenarioValidationError):
        # -0.999 is the exclusive lower bound (demand would hit ~0 only at -1)
        validate_params(config.DEMAND_SHOCK, {"demand_adjustment_pct": -0.999})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.DEMAND_SHOCK, {"demand_adjustment_pct": float("nan")})
    assert validate_params(
        config.DEMAND_SHOCK, {"demand_adjustment_pct": -0.95}) is not None
    assert validate_params(
        config.DEMAND_SHOCK, {"demand_adjustment_pct": 10.0}) is not None
    with pytest.raises(ScenarioValidationError):
        validate_params(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.1,
                                              "sneaky": 1.0})


def test_lead_time_delta_must_keep_lt_enforceable():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.LEAD_TIME_CHANGE, {"lead_time_delta_days": -7.0},
                        base_lead_time_days=7.0)   # new LT = 0 < 1
    with pytest.raises(ScenarioValidationError):
        validate_params(config.LEAD_TIME_CHANGE, {})  # missing param
    # boundary: base 7 + delta -6 = 1 day (valid, enforceable)
    assert validate_params(
        config.LEAD_TIME_CHANGE, {"lead_time_delta_days": -6.0},
        base_lead_time_days=7.0) is not None
    assert validate_params(
        config.LEAD_TIME_CHANGE, {"lead_time_delta_days": 3.0},
        base_lead_time_days=7.0) is not None


def test_service_level_target_strict_bounds():
    for bad in (0.0, 1.0, -0.1, 1.1, float("nan")):
        with pytest.raises(ScenarioValidationError):
            validate_params(config.SERVICE_LEVEL_CHANGE,
                            {"service_level_target": bad})
    for good in (0.50, 0.90, 0.999999):
        assert validate_params(
            config.SERVICE_LEVEL_CHANGE,
            {"service_level_target": good}) is not None


def test_reorder_policy_requires_both_and_sane_cap():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.REORDER_POLICY, {"reorder_qty_multiple": 3.0})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.REORDER_POLICY, {"max_order_qty_coverage_days": 20.0})
    # multiple above its cap is a meaningless combination -> invalid
    with pytest.raises(ScenarioValidationError):
        validate_params(config.REORDER_POLICY,
                        {"reorder_qty_multiple": 25.0,
                         "max_order_qty_coverage_days": 10.0})
    assert validate_params(
        config.REORDER_POLICY,
        {"reorder_qty_multiple": 14.0, "max_order_qty_coverage_days": 28.0}
    ) is not None


def test_ranking_weights_must_sum_to_one():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.STOCKOUT_RISK,
                        {"volume": 0.1, "volatility": 0.1, "stockout_prob": 0.1,
                         "service_gap": 0.1, "urgency": 0.1})
    with pytest.raises(ScenarioValidationError):
        # partial overrides leave default weights summing past 1 -> rejected
        validate_params(config.STOCKOUT_RISK,
                        {"stockout_prob": 0.5, "service_gap": 0.5})
    # an explicit full weight set (incl. zeroed defaults) is accepted
    weights = validate_params(
        config.STOCKOUT_RISK,
        {"stockout_prob": 0.5, "service_gap": 0.5,
         "volume": 0.0, "volatility": 0.0, "urgency": 0.0},
    )
    assert weights["stockout_prob"] == pytest.approx(0.5)
    assert weights["service_gap"] == pytest.approx(0.5)
    assert weights["volume"] == pytest.approx(0.0)


def test_ranking_source_scenario_must_be_string():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.EXCESS_RISK, {"source_scenario": ""})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.EXCESS_RISK, {"source_scenario": 42})
    # source_scenario 'baseline' is valid; ranking returns the effective weights
    assert validate_params(
        config.EXCESS_RISK, {"source_scenario": "baseline"}) == dict(
            config.EXCESS_RISK_WEIGHTS)


def test_tradeoff_requires_target_and_rejects_unknowns():
    with pytest.raises(ScenarioValidationError):
        validate_params(config.ACTION_TRADEOFF, {"baseline_scenario": "b"})
    with pytest.raises(ScenarioValidationError):
        validate_params(config.ACTION_TRADEOFF,
                        {"target_scenario": "x", "not_a_param": 1.0})
    assert validate_params(
        config.ACTION_TRADEOFF, {"target_scenario": "demand_shock_p10"}) is not None
    # explicit positive monetary assumptions are allowed
    assert validate_params(
        config.ACTION_TRADEOFF,
        {"target_scenario": "x", "unit_holding_cost": 0.5,
         "stockout_penalty_per_unit": 2.0, "holding_period_days": 28}) is not None
    with pytest.raises(ScenarioValidationError):
        validate_params(config.ACTION_TRADEOFF,
                        {"target_scenario": "x", "unit_holding_cost": -1.0})


def test_full_definition_validation():
    ok = _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.10})
    assert validate_scenario_definition(ok) is ok
    with pytest.raises(ScenarioValidationError):
        validate_scenario_definition(_defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.10}, name=" "))
    with pytest.raises(ScenarioValidationError):
        validate_scenario_definition(
            ScenarioDefinition("x", config.DEMAND_SHOCK,
                               {"demand_adjustment_pct": 0.10},
                               base_assumption_set_id=0))


def test_validation_is_deterministic():
    # validation has no side effects / no randomness
    a = validate_scenario_definition(
        _defn(config.REORDER_POLICY,
              {"reorder_qty_multiple": 14.0, "max_order_qty_coverage_days": 28.0}))
    b = validate_scenario_definition(
        _defn(config.REORDER_POLICY,
              {"reorder_qty_multiple": 14.0, "max_order_qty_coverage_days": 28.0}))
    assert a == b