# KPI Definitions — Canonical SQL Analytical Layer

**Phase:** 3B — SQL Analytical Layer (implemented)
**Source:** Phase 2 warehouse (`fact_daily_sales`, `fact_weekly_price`, `dim_date`, `dim_product`, `dim_store`, `dim_category`, `dim_department`)

This document is the **single canonical source of truth** for every KPI implemented
under `sql/analytics/`. Each KPI has exactly one tested definition. Aggregations are
validated to reconcile additively back to the Phase 2 facts (see `tests/sql/test_phase3_analytics.py`).

---

## 0. Foundational facts & the weekly revenue anchor

### 0.1 Facts
- `fact_daily_sales` — grain `(product, store, day)`, `units_sold`, `demand_source='observed'`.
- `fact_weekly_price` — grain `(product, store, week)`, `sell_price` (numeric).
- `dim_date.date_id` == M5 day index (`d_1..d_1941`); `dim_date.wm_yr_wk` == natural week;
  `dim_date.week_id` == ordinal week (1..282).

### 0.2 The weekly revenue anchor (`mv_weekly_sales`)
Because price is constant within a week (per product/store), **revenue is computed once at the
weekly grain** and is additive to every higher grain:

```
revenue(product, store, week) = units(product, store, week) × sell_price(product, store, week)
```

where `units = Σ_days_in_week(units_sold)` and `sell_price` is the store-level weekly price joined
on `wm_yr_wk`. This is materialized as `mv_weekly_sales` (grain `(product_surr_id, store_surr_id, wm_yr_wk)`)
so the 59M-row daily scan is executed **once**, and every downstream KPI/rollup reads the small weekly fact —
never re-scanning `fact_daily_sales`.

**Caveat (documented):** price rows exist only where an item was sold in a store (`6,841,121` price rows
vs. full cross-product 3049×10×282). For a `(product, store, week)` that has units but no price row,
`revenue` is `NULL` (unpriced) — those units still count in every **units** KPI, but are excluded from
**revenue** totals. Reconciliation tests verify **units** always matches the Phase 2 total exactly and that
**revenue** is internally consistent (`Σ units×price` recomputed independently).

---

## 1. Revenue

**Definition (weekly grain, additive):**
```
revenue = SUM( units × sell_price )
```
at any grain, by rolling up `mv_weekly_sales`. NULL (unpriced) rows contribute nothing.

| Object | Grain | Purpose |
|---|---|---|
| `mv_weekly_sales` | product×store×week | precomputed units, sell_price, revenue |
| `v_revenue` | any rollup | revenue per chosen grain |

## 2. Units

**Definition (fully additive at every grain):**
```
units = SUM(units_sold)      -- from fact_daily_sales (or mv_weekly_sales)
```
Reconciles exactly to `66,927,173` observed units across all 1,941 observed days.

## 3. Price

**Definition:** `sell_price` is measured at the **weekly** grain (per product/store). Aggregated
(weighted) price at higher grains:
```
weighted_price = revenue / units      -- when both are non-null
simple_avg_price = AVG(sell_price)   -- unweighted (informational only)
```
No daily price is invented; price is only ever the observed weekly value.

## 4. Growth (WoW / QoQ / YoY)

Growth is period-over-period percent change, always forward-compatible, computed on contiguous periods
from the materialized weekly fact:

```
growth = (current_period_value / prior_period_value - 1) × 100
```
- **WoW** — weekly totals vs the immediately preceding `wm_yr_wk` (`LAG` over full 282-week span).
- **QoQ** — quarterly totals vs previous quarter.
- **YoY** — yearly totals vs previous year.

| View | Content |
|---|---|
| `v_growth_wow` | weekly units & revenue with WoW % |
| `v_growth_qoq` | quarterly units & revenue with QoQ % |
| `v_growth_yoy` | yearly units & revenue with YoY % |

## 5. Product contribution / Pareto

**Definition:** share of total revenue (and units) per product, with cumulative share for Pareto.
```
product_share = product_revenue / total_revenue
cumulative_share = running SUM(product_share) ordered by product_revenue DESC
```
| View | Purpose |
|---|---|
| `v_product_contribution` | per-product units, revenue, share, cumulative share, rank |

## 6. Department & category contribution

**Definition:** share of revenue/units per department and per category. Because every product maps to
exactly one department and one category, `Σ department = Σ category = Σ product = total` (additive).
| View | Purpose |
|---|---|
| `v_department_contribution` | per-department (+category) share |
| `v_category_contribution` | per-category share |

## 7. Store & state contribution

**Definition:** share of revenue/units per store and per state, rolling up via `dim_store.state_id` /
`region_id`. `Σ store = Σ state = total` (additive).
| View | Purpose |
|---|---|
| `v_store_contribution` | per-store (+state, +region) share |
| `v_state_contribution` | per-state share |

## 8. Rollups (daily → weekly → monthly, product → dept → category, store → state)

All rollups **reconcile additively** to the base facts; verified by tests.

| View | Rollup |
|---|---|
| `v_rollup_daily` | daily (base, essentially `fact_daily_sales` + dims) |
| `v_rollup_weekly` | weekly units & revenue |
| `v_rollup_monthly` | monthly units & revenue (year, month) |
| `v_product_contribution` | product→department→category chain |
| `v_store_contribution` / `v_state_contribution` | store→state→region chain |

## 9. Demand statistics (product-store demand layer)

Materialized into the existing `fact_product_store_demand` (grain `(product, store, analysis_window)`),
populated **once** by a single set-based aggregation over `fact_daily_sales`:

| Column | Definition |
|---|---|
| `total_units` | `SUM(units_sold)` |
| `analysis_window` | `'observed_full'` (fixed for the full observed span) |
| `series_start` / `series_end` | `MIN(date_id)` / `MAX(date_id)` |
| `mean_daily_units` | `total_units / (series_end - series_start + 1)` |
| `std_daily_units` | `STDDEV(units_sold)` |
| `cv` | `std_daily_units / mean_daily_units` (NULL when mean = 0) |
| `zero_demand_days` | `COUNT(*) FILTER (units_sold = 0)` |
| `demand_growth_rate` | `mean(last 28 observed days) / mean(prior 28 days) - 1` |
| `trend_slope` | `REGR_SLOPE(units_sold, date_id)` |

The 59M-row aggregation runs **once** in Phase 3B and is reused by Phase 3C (demand analysis) and
Phase 3F (safety-stock/reorder) — never recomputed in a Python loop.

## 10. Object inventory

All objects live under `sql/analytics/`; the heavy ones are materialized/bounded:

| Object | Type | Rows (approx) |
|---|---|---|
| `mv_weekly_sales` | materialized view | ~ (product×store×active week) |
| `fact_product_store_demand` | table (existing, populated) | 30,490 |
| `v_revenue`, `v_units` | views | — |
| `v_price_*` | views | — |
| `v_growth_wow/qoq/yoy` | views | — |
| `v_product/department/category/store/state_contribution` | views | — |
| `v_rollup_daily/weekly/monthly` | views | — |
