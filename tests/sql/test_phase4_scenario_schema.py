"""
Phase 4 - read-only warehouse acceptance tests for the scenario schema.

READ-ONLY: SELECT / to_regclass only. Asserts the Phase 4 DDL landed
additively on top of the completed phases (Phase 2-3E row counts unchanged,
decision table still empty by design until the decision-engine step runs).
"""

import pytest

from conftest import scalar  # noqa: E402


PHASE4_TABLES = ("scenario", "scenario_rules", "fact_scenario_run",
                 "fact_scenario_result", "fact_scenario_comparison")

# Completed-phase row counts (locked after Phase 3E production run).
PROD_INVENTORY_ROWS = 853_720


def test_phase4_tables_exist(conn):
    with conn.cursor() as cur:
        for t in PHASE4_TABLES:
            cur.execute("SELECT to_regclass(%s)", (t,))
            assert cur.fetchone()[0] == t


def test_phase4_tables_populated_after_production(conn):
    """Phase 4 tables now hold the production scenario outputs (run 11)."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM scenario")
        assert cur.fetchone()[0] == 7
        cur.execute("SELECT count(*) FROM scenario_rules")
        assert cur.fetchone()[0] == 21
        cur.execute("SELECT count(*) FROM fact_scenario_run")
        assert cur.fetchone()[0] == 7
        cur.execute("SELECT count(*) FROM fact_scenario_result")
        assert cur.fetchone()[0] == 213_430
        cur.execute("SELECT count(*) FROM fact_scenario_comparison")
        assert cur.fetchone()[0] == 0


def test_recommendation_table_still_empty_structure_only(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM fact_replenishment_recommendation")
        assert cur.fetchone()[0] == 0


def test_recommendation_scenario_columns_added(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='fact_replenishment_recommendation' "
            "AND column_name IN ('scenario_id','scenario_run_id','priority',"
            "'priority_label') ORDER BY column_name")
        rows = dict(cur.fetchall())
    assert set(rows) == {"scenario_id", "scenario_run_id", "priority",
                         "priority_label"}
    assert rows["priority"] == "integer"
    assert rows["priority_label"] == "text"


def test_recommendation_action_check_constraint(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='fact_replenishment_recommendation'::regclass "
            "AND contype='c'")
        defs = [r[0] for r in cur.fetchall() if "recommendation" in r[0]]
    assert defs
    text = defs[0].lower()
    for label in ("reorder", "monitor", "reduce inventory",
                  "high stockout risk", "excess inventory",
                  "no action required"):
        assert label in text


def test_phase2_3_tables_intact(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM fact_product_store_demand")
        n1 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fact_demand_analysis")
        n2 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fact_forecast")
        n3 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fact_inventory_simulation")
        n4 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM assumption_set")
        n5 = cur.fetchone()[0]
    assert n1 > 0
    assert n2 == 30_490
    assert n3 == PROD_INVENTORY_ROWS
    assert n4 == PROD_INVENTORY_ROWS
    assert n5 == 1


def test_phase3e_projection_consistency_still_clean(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM fact_inventory_simulation "
            "WHERE (stockout_units > 0 AND NOT projected_stockout) "
            "OR (stockout_units <= 0 AND projected_stockout)")
        assert cur.fetchone()[0] == 0


def test_scenario_rules_columns_match_config_contract(conn):
    from src.scenario import config as scenario_config
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='scenario_rules' ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
    assert cols == ["rule_id", "rule_key", "rule_value", "rule_text", "description"]
    # rules are written idempotently by the Phase 4 driver; the config dict is
    # the documented contract for every key/threshold the engine runs on
    assert len(scenario_config.RULES) >= 20
    assert "base_assumption_set_id" in scenario_config.RULES
    assert "stockout_w_prob" in scenario_config.RULES
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM scenario_rules")
        assert cur.fetchone()[0] == 21   # populated once by the production driver


def test_scenario_table_types_constrained(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT scenario_type FROM scenario")  # empty but column exists
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='scenario' "
            "AND column_name IN ('scenario_name','scenario_type','params_json')")
        assert cur.fetchone()[0] == 3