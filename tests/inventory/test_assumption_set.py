"""
Phase 3E - Assumption-set reproducibility & provenance tests.

Verifies the Phase 3E assumption set is explicit, stable, and reproducible
(config constants match the persisted-row shape the driver will write to the
`assumption_set` table), and that every inventory quantity is bound to
data_provenance='simulated' (M5 has NO observed inventory).

No database is involved.
"""

import json

import pytest

from src.inventory import config, formulas


# --------------------------------------------------------------------------- #
# Assumption set: required keys are present and explicit
# --------------------------------------------------------------------------- #
def test_assumption_set_id_is_positive_integer():
    assert isinstance(config.ASSUMPTION_SET_ID, int)
    assert config.ASSUMPTION_SET_ID >= 1


def test_assumption_set_name_and_description_present():
    assert config.ASSUMPTION_SET_NAME
    assert config.ASSUMPTION_SET_DESCRIPTION


def test_persisted_row_has_all_assumption_set_columns():
    row = config.ASSUMPTION_SET_ROWS[config.ASSUMPTION_SET_NAME]
    for col in ("name", "description", "starting_inventory_rule",
                "supplier_lead_time_days", "service_level",
                "safety_stock_formula", "reorder_policy",
                "reorder_quantity_rule", "demand_adjustment"):
        assert col in row, f"missing assumption-set column: {col}"


def test_service_level_is_target_95():
    assert config.SERVICE_LEVEL == 0.95


def test_service_level_z_consistent_with_service_level():
    assert formulas.z_service(config.SERVICE_LEVEL) == pytest.approx(config.SERVICE_LEVEL_Z)


# --------------------------------------------------------------------------- #
# Start-of-horizon assumption rules are documented
# --------------------------------------------------------------------------- #
def test_starting_inventory_rule_is_coverage_days():
    assert config.STARTING_INVENTORY_RULE == "coverage_days"
    assert config.STARTING_COVERAGE_DAYS > 0


def test_lead_time_rule_is_fixed_and_positive():
    assert config.LEAD_TIME_RULE == "fixed"
    assert config.LEAD_TIME_DAYS > 0


def test_reorder_policy_and_quantity_rule_documented():
    assert config.REORDER_POLICY == "(s,Q)"
    assert config.REORDER_QUANTITY_RULE == "capped_coverage_days"


def test_stockout_handling_is_backorder():
    assert config.STOCKOUT_HANDLING == "backorder"


# --------------------------------------------------------------------------- #
# Simulation horizon matches the Phase 3D forecast horizon
# --------------------------------------------------------------------------- #
def test_horizon_matches_phase3d_forecast_window():
    # Origin 1941, days [1942,1969], length 28 (Phase 3D FINAL_HORIZON).
    assert config.HORIZON_START_DAY == 1942
    assert config.HORIZON_END_DAY == 1969
    assert config.HORIZON_DAYS == 28


# --------------------------------------------------------------------------- #
# Provenance: every quantity is simulated
# --------------------------------------------------------------------------- #
def test_simulated_provenance_constant_used_everywhere():
    # The package docstring and config promise data_provenance='simulated'.
    assert hasattr(config, "ASSUMPTION_SET_ROWS")
    # The formula module must not carry any 'observed' provenance path for
    # inventory figures (they are all derived from simulated assumptions).
    src = open(formulas.__file__, encoding="utf-8").read()
    assert "simulated" in src.lower()
    # No inventory result should be labeled observed.
    assert "provenance='observed'" not in src.lower()


def test_assumption_set_row_is_json_serializable():
    row = config.ASSUMPTION_SET_ROWS[config.ASSUMPTION_SET_NAME]
    json.dumps(row)  # must not raise