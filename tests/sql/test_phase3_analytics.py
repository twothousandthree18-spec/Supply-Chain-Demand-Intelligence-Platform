"""
Supply Chain & Demand Intelligence Platform
Phase 3B - SQL Analytical Layer tests (READ-ONLY).

Verifies the Phase 3B analytical objects against the Phase 2 warehouse:
  * the materialized weekly revenue anchor (mv_weekly_sales) exists & is populated,
  * the product-store demand statistics layer (fact_product_store_demand) is
    populated once (30,490 series),
  * every canonical KPI view exists,
  * KPI correctness + ADDITIVE reconciliation back to Phase 2 facts.

These tests SELECT only; they never run DDL, DML, or ETL. They deliberately read
the small materialized weekly anchor rather than re-scanning the 59M-row
fact_daily_sales (the whole reason Phase 3B materializes).

Canonical definitions: docs/kpi_definitions.md
"""

import pytest

from conftest import scalar  # noqa: E402

OBSERVED_UNITS = 66_927_173
PRODUCTS = 3049
STORES = 10
DEMAND_SERIES = 30_490  # products * stores

# All analytical objects created by Phase 3B.
VIEWS = [
    "v_weekly", "v_units", "v_revenue", "v_price_weekly",
    "v_growth_wow", "v_growth_qoq", "v_growth_yoy",
    "v_product_contribution", "v_department_contribution",
    "v_category_contribution", "v_store_contribution", "v_state_contribution",
    "v_rollup_daily", "v_rollup_weekly", "v_rollup_monthly",
    "v_rollup_product_hierarchy", "v_rollup_store_hierarchy",
]


# --------------------------------------------------------------------------- #
# Object existence
# --------------------------------------------------------------------------- #

def test_mv_weekly_sales_exists(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM pg_matviews WHERE matviewname='mv_weekly_sales'")
    assert cur.fetchone()[0] == 1, "mv_weekly_sales materialized view missing"


def test_mv_weekly_sales_unique_index(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_indexes
        WHERE indexname='uq_mv_weekly_sales' AND tablename='mv_weekly_sales'""")
    assert cur.fetchone()[0] == 1, "unique index uq_mv_weekly_sales missing"


@pytest.mark.parametrize("view", VIEWS)
def test_kpi_view_exists(conn, view):
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.relname=%s AND c.relkind='v' AND n.nspname='public'", (view,))
    assert cur.fetchone()[0] == 1, f"analytical view missing: {view}"


# --------------------------------------------------------------------------- #
# Row counts
# --------------------------------------------------------------------------- #

def test_mv_weekly_sales_populated(conn):
    assert scalar(conn.cursor(), "SELECT count(*) FROM mv_weekly_sales") > PRODUCTS * STORES


def test_demand_stats_series_count(conn):
    """One aggregate row per (product, store) series, all with the fixed window."""
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE analysis_window='observed_full'),
               count(*) FILTER (WHERE data_provenance='derived')
        FROM fact_product_store_demand""")
    n, win, prov = cur.fetchone()
    assert n == DEMAND_SERIES, f"expected {DEMAND_SERIES} demand series, got {n}"
    assert win == DEMAND_SERIES, "every series must use window 'observed_full'"
    assert prov == DEMAND_SERIES, "every series must be provenance 'derived'"


# --------------------------------------------------------------------------- #
# Reconciliation invariants (Phase 2 must remain the source of truth)
# --------------------------------------------------------------------------- #

def test_units_reconcile_weekly_anchor(conn):
    """mv_weekly_sales.units == Phase 2 observed daily total."""
    assert scalar(conn.cursor(), "SELECT sum(units) FROM mv_weekly_sales") == OBSERVED_UNITS


def test_units_reconcile_demand_layer(conn):
    """fact_product_store_demand.total_units == Phase 2 observed daily total."""
    assert scalar(conn.cursor(), "SELECT sum(total_units) FROM fact_product_store_demand") \
        == OBSERVED_UNITS


def test_daily_rollup_reconciles(conn):
    """v_rollup_daily (observed) sums to the Phase 2 total."""
    assert scalar(conn.cursor(), "SELECT sum(units_sold) FROM v_rollup_daily") == OBSERVED_UNITS


def test_weekly_rollup_reconciles(conn):
    assert scalar(conn.cursor(), "SELECT sum(units) FROM v_rollup_weekly") == OBSERVED_UNITS


def test_monthly_rollup_reconciles(conn):
    assert scalar(conn.cursor(), "SELECT sum(units) FROM v_rollup_monthly") == OBSERVED_UNITS


def test_revenue_internally_consistent(conn):
    """store revenue == sum(units*sell_price) within the anchor (cheap, no rescan)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT sum(units*sell_price), sum(revenue) FROM mv_weekly_sales")
    recomputed, stored = cur.fetchone()
    assert stored is not None and stored > 0, "revenue must be positive"
    assert abs(recomputed - stored) < 1.0, "stored revenue diverges from units*price"


def test_revenue_has_no_unpriced_units(conn):
    """Every (product,store,week) with units has a price, so revenue reconciles fully."""
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FILTER (WHERE revenue IS NULL AND units > 0) FROM mv_weekly_sales")
    assert cur.fetchone()[0] == 0


def test_contribution_sums_to_100(conn):
    """Product revenue shares sum to 100% (Pareto denominator is total revenue)."""
    for view in ["v_product_contribution", "v_department_contribution",
                 "v_category_contribution", "v_store_contribution", "v_state_contribution"]:
        assert float(scalar(conn.cursor(), f"SELECT sum(revenue_share_pct) FROM {view}")) \
            == pytest.approx(100.0, abs=0.1), view


def test_product_contribution_pareto_order(conn):
    """Cumulative share must be monotonic non-decreasing with rank (desc by revenue)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT rank, revenue_share_pct, cumulative_share_pct
        FROM v_product_contribution
        ORDER BY rank""")
    rows = cur.fetchall()
    assert rows, "product contribution must not be empty"
    assert rows[0][0] == 1
    prev_cum = -1.0
    for _rank, _share, cum in rows:
        cum = float(cum)
        assert cum >= prev_cum - 0.001, "cumulative share must be non-decreasing"
        prev_cum = cum
    assert abs(float(rows[-1][2]) - 100.0) < 0.1, "final cumulative share must be ~100%"


def test_hierarchy_rollups_additive(conn):
    """sum of per-product >> sum of per-department >> sum of per-store (all = total)."""
    prod = scalar(conn.cursor(), "SELECT sum(units) FROM v_rollup_product_hierarchy")
    store = scalar(conn.cursor(), "SELECT sum(units) FROM v_rollup_store_hierarchy")
    assert prod == OBSERVED_UNITS and store == OBSERVED_UNITS


def test_demand_layer_series_extent(conn):
    """Every series spans the full observed window [1, 1941] (all days present)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FILTER (WHERE series_start=1 AND series_end=1941)
        FROM fact_product_store_demand""")
    assert cur.fetchone()[0] == DEMAND_SERIES
