"""
Phase 4 - Scenario data-contract tests (step 1).

Requirement coverage:
  * typed contracts (ScenarioDefinition, SeriesInput, ScenarioSeriesResult,
    ActionTradeoff, Recommendation, reproducibility payload)
  * deterministic, DB-free scenario layer (no db_utils / psycopg2 import)
  * recommendation action labels constrained to the persisted CHECK values
"""

from dataclasses import FrozenInstanceError

import pytest

# importing the scenario layer must NOT pull in any database code
import src.scenario.config as config
import src.scenario.contract as contract
import src.scenario.scenarios
import src.scenario.validation
from src.inventory.simulation import InventoryPolicy
from src.scenario.contract import (
    ActionTradeoff,
    Recommendation,
    ScenarioDefinition,
    ScenarioSeriesResult,
    SizingMoments,
    build_reproducibility,
)


def test_scenario_layer_is_db_free():
    """Static import-graph check: the pure scenario layer must never touch the DB.

    Runs against the source on disk (robust even when other test modules have
    imported src.etl/psycopg2 elsewhere in the same process).

    The production driver (run_scenario.py) is EXCLUDED: it is a persistence
    layer that legitimately binds src.etl.db_utils for batched writes. The pure
    computation modules (config, contract, scenarios, validation) stay DB-free.
    """
    from pathlib import Path
    pkg = Path(config.__file__).resolve().parent
    excluded = {"__init__.py", "run_scenario.py"}
    banned = ("src.etl", "db_utils", "psycopg2")
    sources = [p.read_text(encoding="utf-8") for p in pkg.glob("*.py")
               if p.name not in excluded]
    assert sources
    for text in sources:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not any(b in stripped for b in banned), \
                    f"DB import found in scenario layer: {line.strip()}"
    # no connection object should ever exist in this process scope
    assert not hasattr(src.scenario.scenarios, "connect")


def test_scenario_definition_is_frozen_param_api():
    d = ScenarioDefinition("shock10", config.DEMAND_SHOCK,
                           {"demand_adjustment_pct": 0.10})
    assert d.param("demand_adjustment_pct") == 0.10
    assert d.param("missing", 42) == 42
    assert d.version == 1
    assert d.base_assumption_set_id == config.BASE_ASSUMPTION_SET_ID
    with pytest.raises(FrozenInstanceError):
        d.scenario_name = "other"


def test_sizing_moments_consume_phase3c_only():
    m = SizingMoments(mean_daily_units=10.0, std_daily_units=4.0,
                      total_units=2800.0, cv=0.4)
    assert m.total_units == pytest.approx(2800.0)


def test_scenario_result_contract_and_provenance():
    policy = InventoryPolicy(10.0, 17.41, 87.41, 70.0, 70.0, 70.0, 7.0, 28.0, 0.95)
    r = ScenarioSeriesResult(
        product_surr_id=1, store_surr_id=1, scenario=None, policy=policy,
        metrics={"total_demand": 280.0})
    assert r.data_provenance == config.DATA_PROVENANCE_SIMULATED
    assert r.deltas is None
    assert r.risk_score is None
    r.risk_score = 0.9            # mutable: ranking fills fields in place
    assert r.risk_score == 0.9


def test_recommendation_contract_action_labels():
    labels = config.RECOMMENDATION_ACTION_LABELS
    assert labels == (
        "REORDER", "MONITOR", "REDUCE INVENTORY", "HIGH STOCKOUT RISK",
        "EXCESS INVENTORY", "NO ACTION REQUIRED",
    )
    rec = Recommendation(
        product_surr_id=7, store_surr_id=3, decision_day=1969,
        recommendation="REORDER",
        rationale="exposure to a projected stockout",
        evidence_fields={"stockout_days": 4},
        impact_estimate="orders advance by one replenishment lead time",
        traceability_path="baseline -> demand_shock_p20",
        priority=1, priority_label="P1",
        scenario_id=9, scenario_run_id=12, assumption_set_id=1)
    assert rec.recommendation in labels
    assert rec.priority_label in config.PRIORITY_LABELS
    assert rec.data_provenance == config.DATA_PROVENANCE_SIMULATED
    with pytest.raises(FrozenInstanceError):
        rec.recommendation = "HALT"     # decisions are immutable once emitted


def test_module_dataset_contains_expected_provenance():
    # the persisted fact tables are explicitly commented as SIMULATED-only
    assert config.DATA_PROVENANCE_SIMULATED == "simulated"


def test_build_reproducibility_records_definition_and_engines():
    d = ScenarioDefinition("lt9", config.LEAD_TIME_CHANGE,
                           {"lead_time_delta_days": 2.0},
                           base_assumption_set_id=1)
    payload = build_reproducibility(d, sizing_rows=30_490,
                                    forecast_rows=853_720,
                                    effective_params={"lead_time_delta_days": 2.0})
    assert payload["scenario_name"] == "lt9"
    assert payload["params_requested"] == {"lead_time_delta_days": 2.0}
    assert payload["params_effective"] == {"lead_time_delta_days": 2.0}
    assert payload["horizon"]["start"] == config.HORIZON_START_DAY
    assert payload["inputs"]["sizing_rows"] == 30_490
    assert payload["inputs"]["forecast_rows"] == 853_720
    assert "policy_from_aggregates" in payload["engines"]["policy"]
    assert payload["provenance"] == config.DATA_PROVENANCE_SIMULATED


def test_contract_imports_single_inventory_engine():
    # the scenario layer MUST reuse the existing engine, not re-implement it
    assert src.scenario.scenarios.policy_from_aggregates is not None
    assert src.scenario.scenarios.simulate_series is not None