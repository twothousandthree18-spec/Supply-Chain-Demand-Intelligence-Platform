"""
Supply Chain & Demand Intelligence Platform
Phase 3A - Foundation database-object tests (READ-ONLY).

Verifies the Phase 3A foundation objects created for the derived/simulated
warehouse layers:
  * the Phase 3 fact tables exist with the expected column shape,
  * the Final state of the completed-phase facts is locked (populated by
    3B/3D/3E),
  * the intended referential-integrity FKs are enforced,
  * the Phase 3 analytical indexes exist,
  * and that the Phase 2 OBSERVED warehouse is untouched (still populated).

These tests SELECT only; they never run DDL, DML, or ETL.
"""

import pytest

from conftest import scalar  # noqa: E402

PHASE3_TABLES = [
    "fact_product_store_demand",
    "fact_forecast",
    "fact_forecast_evaluation",
    "fact_inventory_simulation",
]
GOVERNANCE_TABLES = ["model_registry", "assumption_set"]


# --------------------------------------------------------------------------- #
# Table existence + column shape
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("table", PHASE3_TABLES + GOVERNANCE_TABLES)
def test_phase3_table_exists(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE relname=%s AND n.nspname='public'",
        (table,),
    )
    assert cur.fetchone()[0] == 1, f"Phase 3 table missing: {table}"


@pytest.mark.parametrize(
    "table,expected",
    [
        ("fact_product_store_demand",
         ["demand_stat_id", "product_surr_id", "store_surr_id",
          "analysis_window", "series_start", "series_end", "total_units",
          "mean_daily_units", "std_daily_units", "cv", "zero_demand_days",
          "demand_growth_rate", "trend_slope", "data_provenance"]),
        ("fact_forecast",
         ["forecast_id", "model_id", "product_surr_id", "store_surr_id",
          "forecast_origin", "forecast_horizon", "forecast_date",
          "forecast_value", "lower_bound", "upper_bound", "is_final",
          "data_provenance"]),
        ("fact_forecast_evaluation",
         ["eval_id", "model_id", "product_surr_id", "store_surr_id",
          "validation_start", "validation_end", "mae", "rmse", "wmae",
          "wrmse", "abs_error", "bias", "data_provenance"]),
        ("fact_inventory_simulation",
         ["sim_id", "assumption_set_id", "product_surr_id", "store_surr_id",
          "day_id", "starting_inventory", "demand_forecast",
          "lead_time_demand", "safety_stock", "reorder_point",
          "inventory_position", "on_hand", "orders_placed", "reorder_qty",
          "projected_stockout", "stockout_units", "excess_inventory",
          "days_of_inventory", "service_level_achieved", "data_provenance"]),
    ],
)
def test_phase3_table_columns(conn, table, expected):
    cur = conn.cursor()
    cur.execute("""
        SELECT string_agg(a.attname, ',' ORDER BY a.attnum)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        WHERE c.relname=%s AND a.attnum>0 AND NOT a.attisdropped""", (table,))
    cols = (cur.fetchone()[0] or "").split(",")
    for c in expected:
        assert c in cols, f"column {c} missing from {table}"


def test_phase3_facts_populated_by_completed_phases(conn):
    """Completed-phase population guard (final state).

    Phase 3D/3E populate the forecast/evaluation/simulation facts; this guards
    the locked row counts so later phases (Phase 4) never disturb them.
    """
    expected = {
        "fact_forecast": 853720,             # 30,490 series x 28-day horizon
        "fact_forecast_evaluation": 122088,  # Phase 3D model evaluation rows
        "fact_inventory_simulation": 853720, # Phase 3E final production run
    }
    for table, rows in expected.items():
        assert scalar(conn.cursor(), f"SELECT count(*) FROM {table}") == rows, table


# --------------------------------------------------------------------------- #
# Provenance columns use the allowed tripartition
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("table", PHASE3_TABLES)
def test_phase3_provenance_check(conn, table):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_constraint
        WHERE conrelid = %s::regclass AND conname LIKE 'chk%%_prov'
          AND pg_get_constraintdef(oid) LIKE '%%observed%%'""", (table,))
    assert cur.fetchone()[0] == 1, f"provenance CHECK missing on {table}"


# --------------------------------------------------------------------------- #
# Referential integrity FKs (Phase 3A additions)
# --------------------------------------------------------------------------- #

def test_forecast_fk_to_model_registry(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_constraint c
        JOIN pg_class c1 ON c1.oid=c.conrelid
        JOIN pg_class c2 ON c2.oid=c.confrelid
        WHERE c.contype='f' AND c.conname='fk_fcast_model'
          AND c1.relname='fact_forecast' AND c2.relname='model_registry'""")
    assert cur.fetchone()[0] == 1, "fact_forecast.model_id -> model_registry FK missing"


def test_forecast_evaluation_fk_to_model_registry(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_constraint c
        JOIN pg_class c1 ON c1.oid=c.conrelid
        JOIN pg_class c2 ON c2.oid=c.confrelid
        WHERE c.contype='f' AND c.conname='fk_feval_model'
          AND c1.relname='fact_forecast_evaluation' AND c2.relname='model_registry'""")
    assert cur.fetchone()[0] == 1, "fact_forecast_evaluation.model_id -> model_registry FK missing"


def test_inventory_simulation_fk_to_assumption_set(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_constraint c
        JOIN pg_class c1 ON c1.oid=c.conrelid
        JOIN pg_class c2 ON c2.oid=c.confrelid
        WHERE c.contype='f' AND c.conname='fk_sim_assumption'
          AND c1.relname='fact_inventory_simulation' AND c2.relname='assumption_set'""")
    assert cur.fetchone()[0] == 1, "fact_inventory_simulation.assumption_set_id FK missing"


# --------------------------------------------------------------------------- #
# Phase 3 analytical indexes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "index",
    ["ix_ffcast_ent_origin", "ix_ffcast_model_final", "ix_ffcast_date",
     "ix_feval_model", "ix_feval_ent", "ix_fsim_assump_ent", "ix_fsim_ent_day"],
)
def test_phase3_indexes_exist(conn, index):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM pg_indexes WHERE indexname=%s", (index,))
    assert cur.fetchone()[0] == 1, f"Phase 3 index missing: {index}"


# --------------------------------------------------------------------------- #
# Phase 2 observed warehouse is untouched (preservation guard)
# --------------------------------------------------------------------------- #

def test_phase2_observed_tables_intact(conn):
    assert scalar(conn.cursor(), "SELECT count(*) FROM fact_daily_sales") == 59181090
    assert scalar(conn.cursor(), "SELECT count(*) FROM fact_weekly_price") == 6841121
    assert scalar(conn.cursor(), "SELECT count(*) FROM dim_product") == 3049
    assert scalar(conn.cursor(), "SELECT count(*) FROM dim_store") == 10
    assert scalar(conn.cursor(), "SELECT count(*) FROM dim_date") == 1969


def test_phase2_observed_demand_total_intact(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT sum(units_sold) FROM fact_daily_sales WHERE demand_source='observed'")
    assert cur.fetchone()[0] == 66927173
