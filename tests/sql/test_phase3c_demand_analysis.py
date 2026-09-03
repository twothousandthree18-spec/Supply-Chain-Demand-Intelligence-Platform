"""
Supply Chain & Demand Intelligence Platform
Phase 3C - Demand analysis DB tests (READ-ONLY).

Verifies the Phase 3C derived demand-analysis layer populated by
src/analytics/run_demand_analysis.py:
  * the 4 derived tables exist and are populated,
  * every row is provenance 'derived' (computed, not observed),
  * the analysis reconciles additively back to Phase 2 observed units,
  * segmentation / risk / trend / growth outputs use only documented values,
  * growth zero-denominator cases are guarded (no meaningless percentages),
  * documented thresholds are persisted in demand_analysis_rules,
  * a successful 'demand_analysis' run is logged to etl_run_log,
  * Phase 2 observed tables are untouched.

These tests SELECT only; they never run DDL, DML, or ETL.
Formulas: docs/demand_analysis.md
"""

import pytest

from conftest import scalar  # noqa: E402

OBSERVED_UNITS = 66_927_173
SERIES = 30_490
WINDOW = "observed_full"


# --------------------------------------------------------------------------- #
# Object existence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("table", [
    "fact_demand_analysis", "fact_demand_seasonality",
    "fact_demand_seasonality_dow", "demand_analysis_rules",
])
def test_phase3c_table_exists(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE relname=%s AND n.nspname='public'", (table,))
    assert cur.fetchone()[0] == 1, f"Phase 3C table missing: {table}"


# --------------------------------------------------------------------------- #
# Row counts & provenance
# --------------------------------------------------------------------------- #
def test_analysis_populated(conn):
    n, prov, win = cur3(conn, """
        SELECT count(*),
               count(*) FILTER (WHERE data_provenance='derived'),
               count(*) FILTER (WHERE analysis_window=%s)
        FROM fact_demand_analysis""", (WINDOW,))
    assert n == SERIES, f"expected {SERIES} analysis rows, got {n}"
    assert prov == SERIES and win == SERIES, "all analysis rows must be derived/observed_full"


def test_every_demand_layer_series_has_analysis_row(conn):
    missing = scalar(conn.cursor(), """
        SELECT count(*) FROM fact_product_store_demand d
        LEFT JOIN fact_demand_analysis a
               ON a.product_surr_id=d.product_surr_id AND a.store_surr_id=d.store_surr_id
        WHERE a.analysis_id IS NULL""")
    assert missing == 0, f"{missing} demand-layer series missing from analysis"


def test_units_reconcile_to_observed(conn):
    assert scalar(conn.cursor(), "SELECT sum(total_units) FROM fact_demand_analysis") == OBSERVED_UNITS


def test_seasonality_populated_and_valid(conn):
    n = scalar(conn.cursor(), "SELECT count(*) FROM fact_demand_seasonality")
    assert n > 0, "no seasonality rows persisted"
    bad_month = scalar(conn.cursor(),
        "SELECT count(*) FROM fact_demand_seasonality WHERE month NOT BETWEEN 1 AND 12")
    bad_idx = scalar(conn.cursor(),
        "SELECT count(*) FROM fact_demand_seasonality WHERE seasonality_index <= 0")
    assert bad_month == 0 and bad_idx == 0


def test_dow_ranges(conn):
    assert scalar(conn.cursor(),
        "SELECT count(*) FROM fact_demand_seasonality_dow WHERE scope_type='all'") == 7
    assert scalar(conn.cursor(),
        "SELECT count(*) FROM fact_demand_seasonality_dow WHERE weekday_num NOT BETWEEN 1 AND 7") == 0


# --------------------------------------------------------------------------- #
# Value domains (documented, reproducible)
# --------------------------------------------------------------------------- #
def test_trend_direction_values(conn):
    assert scalar(conn.cursor(), """
        SELECT count(*) FROM fact_demand_analysis
        WHERE trend_direction NOT IN ('increasing','flat','decreasing')""") == 0


def test_risk_values(conn):
    assert scalar(conn.cursor(), """
        SELECT count(*) FROM fact_demand_analysis
        WHERE risk_category NOT IN ('Critical','High','Moderate','Low')""") == 0


def test_volume_terciles_roughly_even(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FILTER (WHERE segment_volume='Low'),
               count(*) FILTER (WHERE segment_volume='Medium'),
               count(*) FILTER (WHERE segment_volume='High')
        FROM fact_demand_analysis""")
    low, med, high = cur.fetchone()
    assert abs(low - SERIES // 3) < SERIES * 0.05
    assert abs(med - SERIES // 3) < SERIES * 0.05
    assert abs(high - SERIES // 3) < SERIES * 0.05


# --------------------------------------------------------------------------- #
# Growth guards (zero / near-zero denominators)
# --------------------------------------------------------------------------- #
def test_growth_zero_denominator_guarded(conn):
    # when the prior mean is ~0, growth must be marked undefined and NULL
    bad = scalar(conn.cursor(), """
        SELECT count(*) FROM fact_demand_analysis
        WHERE growth_denominator_zero AND (growth_is_defined OR demand_growth_rate IS NOT NULL)""")
    assert bad == 0


def test_growth_defined_has_finite_value(conn):
    bad = scalar(conn.cursor(), """
        SELECT count(*) FROM fact_demand_analysis
        WHERE growth_is_defined AND demand_growth_rate IS NULL""")
    assert bad == 0


# --------------------------------------------------------------------------- #
# Documented thresholds persisted
# --------------------------------------------------------------------------- #
def test_rules_persisted(conn):
    keys = {"volume_quantile_low", "volume_quantile_high", "cv_low", "cv_high",
            "zero_ratio_erratic", "zero_ratio_lumpy", "zero_ratio_intermittent",
            "trend_up_pct", "trend_down_pct", "growth_epsilon",
            "risk_critical", "risk_high", "risk_moderate"}
    cur = conn.cursor()
    cur.execute("SELECT rule_key FROM demand_analysis_rules")
    present = {r[0] for r in cur.fetchall()}
    assert keys <= present, f"missing rules: {keys - present}"


# --------------------------------------------------------------------------- #
# Run audit
# --------------------------------------------------------------------------- #
def test_demand_analysis_run_succeeded(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM etl_run_log
        WHERE pipeline='demand_analysis' AND status='success' AND records_loaded=%s""",
        (SERIES,))
    assert cur.fetchone()[0] >= 1, "no successful demand_analysis run recorded"


# --------------------------------------------------------------------------- #
# Phase 2 untouched
# --------------------------------------------------------------------------- #
def test_phase2_observed_tables_intact(conn):
    assert scalar(conn.cursor(), "SELECT count(*) FROM fact_daily_sales") == 59181090
    assert scalar(conn.cursor(), "SELECT count(*) FROM fact_weekly_price") == 6841121
    assert scalar(conn.cursor(),
        "SELECT sum(units_sold) FROM fact_daily_sales WHERE demand_source='observed'") \
        == OBSERVED_UNITS


def cur3(conn, sql, params):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchone()
