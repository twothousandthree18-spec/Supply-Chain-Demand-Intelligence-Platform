"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Scenario Engine: data contracts.

Step 1 deliverable: the explicit, typed contracts that the scenario engine and
the (later) decision engine obey. Everything here is DB-free and deterministic.

Contracts:
  * ScenarioDefinition  - named, versioned scenario configuration
  * SizingMoments       - per-series Phase 3C demand moments (consumed input)
  * SeriesInput         - one product/store series: moments + forecast demand
  * ScenarioSeriesResult- per-series scenario output (metrics + deltas + risk)
  * ActionTradeoff      - structured scenario-vs-baseline comparison
  * Recommendation      - decision-engine output contract (fields required by
                          the Phase 4 requirement; logic lands in a later step)
  * ScenarioValidationError - rejected invalid parameters/combinations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from src.inventory.simulation import InventoryPolicy

from . import config


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ScenarioError(Exception):
    """Base error for the scenario layer."""


class ScenarioValidationError(ScenarioError, ValueError):
    """An invalid scenario definition/parameter combination was rejected."""


# --------------------------------------------------------------------------- #
# Consumed inputs (Phase 3C / 3D outputs, already materialized)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SizingMoments:
    """Per-series demand moments from fact_demand_analysis (Phase 3C).

    Used ONLY to size the policy via the existing inventory logic
    (src.inventory.simulation.policy_from_aggregates) - never to re-derive
    demand, and never from a scan of the 59M observed fact.
    """

    mean_daily_units: float
    std_daily_units: float
    total_units: float
    cv: float = 0.0


@dataclass(frozen=True)
class SeriesInput:
    """One product/store series: sizing moments + final forecast demand vector.

    `forecast` is the Phase 3D final forecast for days [1942,1969] (28 values).
    """

    product_surr_id: int
    store_surr_id: int
    moments: SizingMoments
    forecast: Sequence[float]


# --------------------------------------------------------------------------- #
# Scenario configuration (Step 1 contract)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScenarioDefinition:
    """A named, versioned, parameterized scenario.

    `params` are validated against the per-type bounds in validation.py and
    persisted as `params_json` in the `scenario` table. Re-running the same
    definition (same name/type/params/assumption set) reproduces the same
    output by construction (deterministic engines only).
    """

    scenario_name: str
    scenario_type: str
    params: Mapping[str, object]
    base_assumption_set_id: int = config.BASE_ASSUMPTION_SET_ID
    description: str = ""
    version: int = 1

    def param(self, key: str, default: object = None) -> object:
        return self.params.get(key, default)


# --------------------------------------------------------------------------- #
# Scenario output (per series)
# --------------------------------------------------------------------------- #
@dataclass
class ScenarioSeriesResult:
    """Per-series scenario output, incl. deltas vs baseline and risk fields.

    `metrics` mirrors the fact_scenario_result columns; `deltas` (delta_*)
    compares against a baseline result when one was provided. Ranking
    scenarios fill risk_score / risk_tier / risk_rank / components.
    """

    product_surr_id: int
    store_surr_id: int
    scenario: Optional[ScenarioDefinition]
    policy: InventoryPolicy
    metrics: dict
    deltas: Optional[dict] = None
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    risk_rank: Optional[int] = None
    components: Optional[dict] = None
    data_provenance: str = config.DATA_PROVENANCE_SIMULATED


# --------------------------------------------------------------------------- #
# Comparison output (scenario 7 - action trade-off)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActionTradeoff:
    """Structured scenario-vs-baseline comparison.

    Uses operational metrics (units, days of inventory, stockout days, service
    level, order quantity). Monetary figures are ONLY present when an explicit
    monetary-cost assumption was supplied in the scenario params; otherwise
    `monetary` is None (no fabricated financial savings are ever produced).
    """

    scenario_name: str
    target_scenario: str
    baseline_scenario: str
    n_series: int
    inventory_exposure: dict
    service_level_effect: dict
    stockout_impact: dict
    excess_impact: dict
    assumptions: tuple
    monetary: Optional[dict] = None
    data_provenance: str = config.DATA_PROVENANCE_SIMULATED


# --------------------------------------------------------------------------- #
# Decision-engine output contract (Step 1 contract; logic in a later step)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Recommendation:
    """Decision-engine output contract.

    Fields required by the Phase 4 requirement: entity identifiers, current/
    baseline state, scenario state, recommended action, priority, reason,
    supporting metrics, scenario_id, assumption_set_id, provenance.

    The recommendation value must be one of
    config.RECOMMENDATION_ACTION_LABELS (mirrors the DB CHECK constraint on
    fact_replenishment_recommendation.recommendation).
    """

    product_surr_id: int
    store_surr_id: int
    decision_day: int
    recommendation: str
    rationale: str
    evidence_fields: dict
    impact_estimate: str
    traceability_path: str
    priority: int
    priority_label: str
    scenario_id: int
    scenario_run_id: int
    assumption_set_id: int
    data_provenance: str = config.DATA_PROVENANCE_SIMULATED


# --------------------------------------------------------------------------- #
# Reproducibility metadata (Step 1 contract; stored as JSON per run)
# --------------------------------------------------------------------------- #
def build_reproducibility(
    definition: ScenarioDefinition,
    *,
    sizing_rows: int,
    forecast_rows: int,
    effective_params: Optional[Mapping[str, object]] = None,
) -> dict:
    """Reproducibility payload written with every scenario run.

    Records the exact scenario definition, effective parameters, input row
    counts (bounded pulls from Phase 3C/3D), the simulation horizon, the
    engines used, and provenance - so any scenario run can be reconstructed.
    """
    return {
        "scenario_name": definition.scenario_name,
        "scenario_type": definition.scenario_type,
        "scenario_version": definition.version,
        "base_assumption_set_id": definition.base_assumption_set_id,
        "params_requested": dict(definition.params),
        "params_effective": dict(effective_params or definition.params),
        "horizon": {
            "start": config.HORIZON_START_DAY,
            "end": config.HORIZON_END_DAY,
            "days": config.HORIZON_DAYS,
        },
        "inputs": {
            "sizing_rows": int(sizing_rows),
            "forecast_rows": int(forecast_rows),
            "source_sizing": "fact_demand_analysis (Phase 3C)",
            "source_forecast": "fact_forecast is_final (Phase 3D)",
        },
        "engines": {
            "policy": "src.inventory.simulation.policy_from_aggregates (Phase 3E)",
            "simulation": "src.inventory.simulation.simulate_series (Phase 3E)",
            "scenario": "src.scenario.scenarios (Phase 4)",
        },
        "provenance": config.DATA_PROVENANCE_SIMULATED,
    }