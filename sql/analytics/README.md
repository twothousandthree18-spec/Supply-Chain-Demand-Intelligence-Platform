# SQL Analytical Layer (Phase 3B)

Canonical KPI definitions: [`docs/kpi_definitions.md`](../../docs/kpi_definitions.md)
Tests: [`tests/sql/test_phase3_analytics.py`](../../tests/sql/test_phase3_analytics.py)

## Files

| File | Contents |
|---|---|
| `10_mv_weekly_sales.sql` | **Materialized weekly revenue anchor** `mv_weekly_sales` (product×store×week). Collapses the 59M-row `fact_daily_sales` scan **once** into ~8.5M weekly rows: `units = Σunits`, `revenue = units × sell_price` joined via `dim_date.wm_yr_wk`. All downstream KPIs read this, never re-scan the fact. |
| `20_demand_stats.sql` | **Product-store demand layer.** Populates `fact_product_store_demand` (30,490 series, window `observed_full`) with one set-based aggregation: total/mean/std/cv, zero-demand days, series extent, growth rate (28d), trend slope. Reused by Phase 3C/3F. Idempotent (DELETE + INSERT per window). |
| `30_kpi_views.sql` | KPI views: units, revenue, price, WoW/QoQ/YoY growth, product/department/category/store/state contribution (Pareto), and daily/weekly/monthly + hierarchy rollups. All read from `mv_weekly_sales` + dimensions. |

## Design principles

- **Materialize once, never rescan** the 59M-row `fact_daily_sales` in Python loops or repeated SQL.
- **Additive reconciliation**: units reconcile exactly to the Phase 2 observed total `66,927,173` at every grain (daily → weekly → monthly → demand layer). Revenue is internally consistent (`stored == Σ units×price`, diff = 0) and, because every sold (product,store,week) has a price row, reconciles fully.
- **Idempotent/bounded** population so a re-run replaces rather than duplicates.
- Provenance `derived` on the computed demand layer; observed facts untouched.
