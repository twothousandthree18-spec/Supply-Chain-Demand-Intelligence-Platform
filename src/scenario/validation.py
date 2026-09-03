"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Scenario Engine: parameter validation.

Deterministic, DB-free validation of scenario definitions BEFORE any
calculation runs. Rejects:

  * unknown scenario types / unknown parameter keys
  * missing required parameters
  * non-finite / out-of-bounds numeric values
  * invalid parameter combinations (e.g. reorder multiple above its cap,
    lead-time deltas that push the lead time below the enforceable minimum)

Validation is the first guard of the "bounded and reproducible" contract: an
invalid definition never reaches the calculators.
"""

from __future__ import annotations

import math
from typing import Mapping

from . import config
from .contract import ScenarioDefinition, ScenarioValidationError


def _as_number(value, key: str) -> float:
    if isinstance(value, bool):
        raise ScenarioValidationError(f"param '{key}' must be numeric, got bool")
    if value is None:
        raise ScenarioValidationError(f"param '{key}' is required and must be numeric")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioValidationError(
            f"param '{key}' must be numeric, got {value!r}") from exc
    if not math.isfinite(v):
        raise ScenarioValidationError(
            f"param '{key}' must be finite, got {value!r}")
    return v


def _require_in(value, key: str, lo: float, hi: float, *,
                exclusive_lo: bool = False, exclusive_hi: bool = False,
                label: str = "") -> float:
    v = _as_number(value, key)
    ok_lo = v > lo if exclusive_lo else v >= lo
    ok_hi = v < hi if exclusive_hi else v <= hi
    if not (ok_lo and ok_hi):
        bounds = (
            f"({lo}, {hi})" if exclusive_lo and exclusive_hi
            else f"[{lo}, {hi}]" if not exclusive_lo and not exclusive_hi
            else f"({'(' if exclusive_lo else '['}{lo}, {hi}{')' if exclusive_hi else ']'}"
        )
        raise ScenarioValidationError(
            f"param '{key}'{f' ({label})' if label else ''} must be in "
            f"{bounds}, got {v!r}")
    return v


def _reject_unknown(params: Mapping[str, object], allowed, scenario_type: str) -> None:
    unknown = set(params) - set(allowed)
    if unknown:
        raise ScenarioValidationError(
            f"scenario_type '{scenario_type}' does not accept parameter(s): "
            + ", ".join(sorted(unknown)))


def _validate_weights(scenario_type: str, params: Mapping[str, object],
                      allowed_keys: tuple, default_weights: dict) -> dict:
    supplied = {k: v for k, v in params.items() if k in allowed_keys}
    if not supplied:
        return default_weights
    weights = dict(default_weights)
    total = 0.0
    for key in allowed_keys:
        if key not in supplied:
            total += weights[key]
            continue
        w = _require_in(supplied[key], f"weight_{key}", 0.0, 1.0,
                        label=f"{scenario_type} weight")
        weights[key] = w
        total += w
    if abs(total - 1.0) > 1e-6:
        raise ScenarioValidationError(
            f"{scenario_type} weights must sum to 1.0, got {total:.6f}")
    return weights


def validate_params(scenario_type: str, params: Mapping[str, object], *,
                    base_lead_time_days: float = config.BASE_LEAD_TIME_DAYS) -> dict:
    """Validate `params` for `scenario_type`; return the effective weights (if any).

    Raises ScenarioValidationError on any violation. Numeric parameters are
    coerced to float; NaN/Inf are always rejected.
    """
    if scenario_type not in config.SCENARIO_TYPES:
        raise ScenarioValidationError(
            f"unknown scenario_type {scenario_type!r}; expected one of "
            + ", ".join(config.SCENARIO_TYPES))

    params = dict(params)

    if scenario_type == config.DEMAND_SHOCK:
        _reject_unknown(params, ("demand_adjustment_pct",), scenario_type)
        if "demand_adjustment_pct" not in params:
            raise ScenarioValidationError(
                "demand_shock requires param 'demand_adjustment_pct'")
        _require_in(params["demand_adjustment_pct"], "demand_adjustment_pct",
                    config.DEMAND_SHOCK_PCT_MIN, config.DEMAND_SHOCK_PCT_MAX,
                    exclusive_lo=True)

    elif scenario_type == config.LEAD_TIME_CHANGE:
        _reject_unknown(params, ("lead_time_delta_days",), scenario_type)
        if "lead_time_delta_days" not in params:
            raise ScenarioValidationError(
                "lead_time_change requires param 'lead_time_delta_days'")
        delta = _as_number(params["lead_time_delta_days"], "lead_time_delta_days")
        new_lt = base_lead_time_days + delta
        if new_lt < config.LEAD_TIME_MIN_DAYS:
            raise ScenarioValidationError(
                f"lead_time_delta_days={delta} pushes lead time to "
                f"{new_lt} days; must stay >= {config.LEAD_TIME_MIN_DAYS} "
                f"(arrival scheduling needs a full day)")

    elif scenario_type == config.SERVICE_LEVEL_CHANGE:
        _reject_unknown(params, ("service_level_target",), scenario_type)
        if "service_level_target" not in params:
            raise ScenarioValidationError(
                "service_level_change requires param 'service_level_target'")
        _require_in(params["service_level_target"], "service_level_target",
                    config.SERVICE_LEVEL_TARGET_MIN, config.SERVICE_LEVEL_TARGET_MAX,
                    exclusive_lo=True, exclusive_hi=True,
                    label="must be strictly between 0 and 1")

    elif scenario_type == config.REORDER_POLICY:
        _reject_unknown(params, ("reorder_qty_multiple",
                                 "max_order_qty_coverage_days"), scenario_type)
        if "reorder_qty_multiple" not in params or \
           "max_order_qty_coverage_days" not in params:
            raise ScenarioValidationError(
                "reorder_policy requires params 'reorder_qty_multiple' AND "
                "'max_order_qty_coverage_days'")
        q = _require_in(params["reorder_qty_multiple"], "reorder_qty_multiple",
                        0.0, 60.0, exclusive_lo=True, label="days of demand per order")
        cap = _require_in(params["max_order_qty_coverage_days"],
                          "max_order_qty_coverage_days", 0.0, 120.0,
                          exclusive_lo=True, label="order-quantity coverage cap")
        if cap < q:
            raise ScenarioValidationError(
                f"invalid reorder_policy combination: reorder_qty_multiple "
                f"({q}) exceeds max_order_qty_coverage_days ({cap}) - the cap "
                f"would make the multiple meaningless")

    elif scenario_type in config.RANKING_SCENARIOS:
        if scenario_type == config.STOCKOUT_RISK:
            allowed = ("source_scenario",) + tuple(config.STOCKOUT_RISK_WEIGHTS)
        else:
            allowed = ("source_scenario",) + tuple(config.EXCESS_RISK_WEIGHTS)
        _reject_unknown(params, allowed, scenario_type)
        if "source_scenario" in params:
            src = params["source_scenario"]
            if not isinstance(src, str) or not src.strip():
                raise ScenarioValidationError(
                    "source_scenario must be a non-empty scenario name "
                    "(or 'baseline')")
        weights = _validate_weights(
            scenario_type, params,
            tuple(k for k in allowed if not k == "source_scenario"),
            config.STOCKOUT_RISK_WEIGHTS if scenario_type == config.STOCKOUT_RISK
            else config.EXCESS_RISK_WEIGHTS)
        return weights

    elif scenario_type == config.ACTION_TRADEOFF:
        allowed = ("target_scenario", "baseline_scenario",
                   "unit_holding_cost", "stockout_penalty_per_unit",
                   "holding_period_days")
        _reject_unknown(params, allowed, scenario_type)
        target = params.get("target_scenario")
        if not isinstance(target, str) or not target.strip():
            raise ScenarioValidationError(
                "action_tradeoff requires param 'target_scenario' "
                "(a scenario name or 'baseline')")
        if "baseline_scenario" in params:
            b = params["baseline_scenario"]
            if not isinstance(b, str) or not b.strip():
                raise ScenarioValidationError("baseline_scenario must be non-empty")
        for key in ("unit_holding_cost", "stockout_penalty_per_unit"):
            if key in params:
                _require_in(params[key], key, 0.0, 1e12,
                            label="monetary assumption (>= 0)")
        if "holding_period_days" in params:
            _require_in(params["holding_period_days"], "holding_period_days",
                        1.0, 365.0, label="holding cost period in days")

    return params


def validate_scenario_definition(
    definition: ScenarioDefinition,
    *,
    base_lead_time_days: float = config.BASE_LEAD_TIME_DAYS,
) -> ScenarioDefinition:
    """Validate a full scenario definition; return it unchanged on success."""
    if not isinstance(definition, ScenarioDefinition):
        raise ScenarioValidationError("expected a ScenarioDefinition")
    name = definition.scenario_name
    if not isinstance(name, str) or not name.strip():
        raise ScenarioValidationError("scenario_name must be a non-empty string")
    validate_params(definition.scenario_type, definition.params,
                    base_lead_time_days=base_lead_time_days)
    if not isinstance(definition.base_assumption_set_id, int) or \
            definition.base_assumption_set_id <= 0:
        raise ScenarioValidationError(
            "base_assumption_set_id must be a positive int")
    return definition