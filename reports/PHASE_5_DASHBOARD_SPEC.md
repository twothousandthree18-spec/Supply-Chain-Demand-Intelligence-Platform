# Phase 5 — Dashboard / BI Presentation: Architecture

**Status:** SPECIFICATION ONLY. No Power BI model, web app, or visuals are built in this document. This is the authoritative design contract the dashboard build step (and any future web app) must implement.

**Locked inputs:** Phases 1–4 are complete and verified. All metrics, tables, and omputed values below are DEFINITIONAL contracts over locked production data (run_id=11 scenario engine success; Phase 3B/3C/3D/3E verified). Nothing here recalculates the 59M-row `fact_daily_sales`; every visualization reads small, already-materialized surfaces and views.

---

## 0. Guiding Principles

1. **Read-only over locked data.** Every page binds to materialized/anchor surfaces (`mv_weekly_sales`, `fact_*` tables, `scenario`/`scenario_rules`, `v_*` views). No new forecasting, inventory, or scenario logic is introduced.
2. **Never re-scan `fact_daily_sales`.** All historical revenue/units come from `mv_weekly_sales` (collapsed once) and its `v_*` rollups. If a measure needs the flat daily sparkline, use `v_rollup_daily` only where the visual explicitly requires daily grain — it reads from the observed fact filtered to a bounded date/product/store slice via dashboard filters (never a full 59M scan).
3. **Simulated vs observed labeling.** Any metric originating from simulation/forecast/scenario carries `data_provenance='simulated'` (or `derived`/`observed`) and MUST be labeled as such in every visual as required by prior phases.
4. **Deterministic measures.** Every KPI has exactly one definition (see §6). Where a measure is demand-weighted, the weight = `total_units_hist` / `total_demand` per the phase-3D convention.
5. **Business-first.** Pages are ordered by decision intent: Overview → Demand → Forecast → Inventory Risk → Stockout/Excess → Scenario Comparison → Prioritized Insights.
6. **No fabrication.** NULL unpriced revenue contributes 0 to revenue but counts in units; growth with a zero/near-zero denominator is shown as "—" (undefined), never manufactured.

---

## 1. Dashboard Pages

| # | Page | Purpose (decision intent) |
|---|------|---------------------------|
| 1 | **Executive Overview** | Control-tower snapshot: total revenue, units, growth, inventory health, top risks. |
| 2 | **Demand Overview** | Characterize demand patterns: trend, seasonality, volatility, volume×volatility risk matrix. |
| 3 | **Forecast Performance** | How good are the forecasts? accuracy (WMAE/WRMSE/biases), model selection, holdout evaluation. |
| 4 | **Inventory Risk** | Simulated inventory state: position, days-of-inventory, service level, excess exposure, risk tiers. |
| 5 | **Stockout & Excess Risk** | The two prioritized risk rankings from Phase 4: stockout_risk_rank and excess_risk_rank. |
| 6 | **Scenario Comparison** | What-if deltas: demand shock, lead-time change, service-level change, reorder-policy change vs baseline. |
| 7 | **Prioritized Operational Insights** | Ranked, filterable action list of the most harmful stockout/excess series with op-notes. |

Each page supports the global dims (product/store/category/department/state/date) and provenance label. Page 7 is the "so-what" landing page for planners.

---

## 2. KPI Catalog by Page

### Page 1 — Executive Overview
| KPI | Definition | Source |
|-----|-----------|--------|
| Total Revenue (period) | `SUM(units × sell_price)` | `v_revenue` / `mv_weekly_sales` |
| Total Units (period) | `SUM(units_sold)` | `v_units` / `v_weekly` |
| Unit WoW / QoQ / YoY % | period-over-period change | `v_growth_*` |
| Revenue WoW / QoQ / YoY % | period-over-period change | `v_growth_*` |
| Revenue share by dept/category/store | additive share | `v_department/category/store_contribution` |
| Product Pareto (Top-N contrib.) | revenue share + cumulative | `v_product_contribution` |
| Avg weighted price | `revenue/units` | `v_price_weekly` |
| Inventory health (avg days-of-inventory, service level) | simulated means | `fact_scenario_result` (baseline run) |
| Total series at stockout / excess risk | `risk_tier IN (High, Critical)` counts | `fact_scenario_result` (risk-rank runs) |

### Page 2 — Demand Overview
| KPI | Definition | Source |
|-----|-----------|--------|
| Demand trend direction | increasing/flat/decreasing | `fact_demand_analysis.trend_direction` |
| Demand growth rate | recent-28d / prior-28d − 1 | `fact_demand_analysis.demand_growth_rate` |
| Volatility (CV) distribution | std/mean, None→High | `fact_demand_analysis.cv` |
| Volume tercile | Low/Medium/High | `fact_demand_analysis.segment_volume` |
| Volatility class | Low/Medium/High | `fact_demand_analysis.segment_volatility` |
| Demand pattern | Smooth/Erratic/Lumpy/Intermittent | `fact_demand_analysis.segment_demand` |
| Risk matrix (volume×volatility) | cell + category | `fact_demand_analysis.risk_cell/risk_category` |
| Seasonality strength & peak/trough month | per-series indices | `fact_demand_seasonality`, `fact_demand_analysis` |
| Day-of-week factors | scope-level DOW indices | `fact_demand_seasonality_dow` |
| Series counts per segment/cell | COUNT | `fact_demand_analysis` (30,490) |

### Page 3 — Forecast Performance
| KPI | Definition | Source |
|-----|-----------|--------|
| MAE / RMSE / WMAE / WRMSE | standard, demand-weighted | `fact_forecast_evaluation` |
| Bias | positive = over-forecast | `fact_forecast_evaluation.bias` |
| Absolute error | | `fact_forecast_evaluation.abs_error` |
| Model selection (naive/snaive/MA/WMA/ETS/SARIMA) | selected model per series | `model_registry.is_selected`, `fact_forecast.model_id` |
| Holdout window coverage | validation_start..end, n_holdout | `fact_forecast_evaluation` |
| Interval width / coverage | lower/upper bounds vs point | `fact_forecast.forecast_value/lower/upper` |
| Forecast vs actual (final horizon) | line/bars | `fact_forecast.is_final` (28-day, M5 origin) |
| Forecast volume total per week | `SUM(forecast_value)` | `fact_forecast` (final) |

### Page 4 — Inventory Risk
| KPI | Definition | Source |
|-----|-----------|--------|
| Inventory position (time series) | `avg_inventory_position` per day | `fact_inventory_simulation` |
| On-hand / on-order / backorder | `on_hand`, `orders_placed`, `projected_stockout` | `fact_inventory_simulation` |
| Days of inventory | `days_of_inventory` | `fact_inventory_simulation` |
| Service level achieved vs target | achieved vs `assumption_set.service_level` | `fact_inventory_simulation` |
| Safety stock / reorder point | policy snapshot | `fact_scenario_result.safety_stock/reorder_point` |
| Total stockout units/days | SUM | `fact_scenario_result` (baseline) |
| Total excess units/days | SUM | `fact_scenario_result` (baseline) |
| Series by risk tier | tier counts | `fact_scenario_result` (rank runs) |

### Page 5 — Stockout & Excess Risk
| KPI | Definition | Source |
|-----|-----------|--------|
| Stockout risk score (0..1) | weighted 5 components | `fact_scenario_result.risk_score` (stockout_risk_rank run) |
| Stockout risk tier | Low/Medium/High/Critical | `fact_scenario_result.risk_tier` |
| Stockout risk rank | 1..30490 | `fact_scenario_result.risk_rank` |
| Excess risk score / tier / rank | weighted 3 components | `fact_scenario_result` (excess_risk_rank run) |
| Top-N risk series table | by risk_rank | `fact_scenario_result` |
| Risk component breakdown | `risk_components` jsonb | `fact_scenario_result` |
| Series count by tier | COUNT | `fact_scenario_result` (both rank runs) |

### Page 6 — Scenario Comparison
| KPI | Definition | Source |
|-----|-----------|--------|
| Scenario total stockout days/units | per scenario | `fact_scenario_result` GROUP BY scenario_run_id |
| Scenario total excess days/units | per scenario | `fact_scenario_result` GROUP BY scenario_run_id |
| Scenario service level / fill rate | per scenario means | `fact_scenario_result` |
| Delta vs baseline (each of the 4 simulated) | `delta_stockout_units`, `delta_excess_days`, `delta_service_level`, `delta_fill_rate`, `delta_avg_inventory_position`, `delta_reorder_frequency` | `fact_scenario_result` |
| Series count per tier delta | risk-tier shift | `fact_scenario_result` (rank vs baseline) |
| Comparison footprint | `n_series`, `horizon_days`, `aggregate_json` | `fact_scenario_comparison` (0 rows today; contract ready) |

### Page 7 — Prioritized Operational Insights
| KPI | Definition | Source |
|-----|-----------|--------|
| Priority list | rank-ordered series (stockout then excess) | `fact_scenario_result` (both rank runs) |
| Risk score & tier | | `fact_scenario_result` |
| Evidence fields | stockout_days/units, excess_days/units, service_level | `fact_scenario_result` |
| Recommended op-note | descriptive text from evidence (no decision-engine logic) | computed in metric layer |
| Filterable by tier/dept/store | | filters |
| Expected impact (qualitative) | based on excess/stockout magnitude | computed in metric layer |

Page 7 is intentionally **no recommendation engine**: it surfaces ranked evidence and a qualitative op-note. The `Recommendation` dataclass / `fact_replenishment_recommendation` remains out of scope until the Phase 4 decision-engine step runs.

---

## 3. Source Tables / Views

| Surface | Grain | Provenance | Used by |
|---------|-------|-----------|---------|
| `mv_weekly_sales` (+ `v_weekly`) | product×store×week | derived | P1 (revenue, Pareto) |
| `v_revenue`, `v_units`, `v_price_weekly` | various | derived/observed | P1 |
| `v_growth_wow/qoq/yoy` | week/quarter/year | derived | P1 |
| `v_product_contribution`, `v_department_contribution`, `v_category_contribution`, `v_store_contribution`, `v_state_contribution` | per entity | derived | P1 |
| `v_rollup_daily/weekly/monthly` | daily/weekly/monthly | observed/derived | P1 sparklines (bounded) |
| `fact_product_store_demand` | product×store×window | derived | P2 (baseline stats) |
| `fact_demand_analysis` (30,490) | product×store×window | derived | P2 |
| `fact_demand_seasonality` (359,181) | product×store×month | derived | P2 |
| `fact_demand_seasonality_dow` | scope×weekday | derived | P2 |
| `fact_forecast` (final 853,720) | product×store×origin×horizon-day | simulated | P3 |
| `fact_forecast_evaluation` (122,088) | product×store×model | simulated | P3 |
| `model_registry` | model | simulated | P3 (model names, is_selected) |
| `assumption_set` | id | observed/config | P3/P4/P6 (service level, rules) |
| `fact_inventory_simulation` (853,720) | product×store×day | simulated | P4 |
| `fact_scenario_result` (213,430) | (scenario_run, product, store) | simulated | P4/P5/P6/P7 |
| `fact_scenario_run` | run | simulated | P6 (run→scenario link, provenance) |
| `scenario` | definition | simulated | P6 (name, type, params) |
| `scenario_rules` | rule | config | P4/P5 (weights, thresholds, bounds) |
| `fact_scenario_comparison` | run-pair | simulated | P6 (0 rows; contract-ready) |
| `dim_product`, `dim_category`, `dim_department` | entity | observed | All filters |
| `dim_store` | entity | observed | All filters |
| `dim_date` | day | observed | All time filters, calendar/events |
| `etl_run_log` | run | — | Provenance/audit display |

Dimension cardinalities: 3,049 products; 10 stores (CA×4, TX×3, WI×3); dims fully conformed. `fact_forecast` matches `fact_inventory_simulation` grain via `(product,store,day_id=forecast_date)`.

---

## 4. Filters & Interactions (global + page-level)

**Global slicers (apply to all pages):**
- Date / period (iso calendar `dim_date`; week `wm_yr_wk`, month, quarter, year)
- Department, Category, Product
- Store, State, Region
- Provenance (observed / derived / simulated) — default all, but **simulated** visuals always labeled

**Page-level controls:**
- P1: period type (WoW/QoQ/YoY toggle), Top-N (Pareto N, e.g. 10/20/50)
- P2: segment selector (volume/volatility/demand pattern/risk cell); scope for DOW factors (all/category/dept/store/state)
- P3: model family / is_selected toggle; horizon/validation window
- P4: assumption set; date range; risk tier filter
- P5: risk type toggle (stockout vs excess); tier filter; Top-N
- P6: scenario selector (baseline vs each perturbed scenario); delta toggle
- P7: tier, dept, store, score threshold; sort key (stockout/excess) — these filters are **pre-filters** applied to the bounded 30,490×2 rank result before ranking display.

**Interactions:**
- Drill-downs: state→store; dept→category→product; period→week→day (bounded).
- Cross-filter between pages via global dims.
- Tooltips: provenance label + risk components (from `risk_components` jsonb).
- P4↔P5↔P6 linked: select a risk series to see its scenario deltas.
- A **"Final forecast (M5-style origin)"** toggle on P3 shows the 28-day final forecast vs observed actual for a selected series.

**Anti-scan rule:** any daily-grain visual receives date/product/store filters **before** touching `v_rollup_daily`; default surfaces are weekly+.

---

## 5. Dashboard Data Contract (single source of truth)

Fixed grain and keys for the semantic model:
- **Grain:** primary fact `fact_scenario_result` keyed by `(scenario_run_id, product_surr_id, store_surr_id)`. Scenario runs joined via `fact_scenario_run.scenario_id → scenario`.
- **Measures** (additive over products/stores; see §6): `Total Stockout Units`, `Total Stockout Days`, `Total Excess Units`, `Total Excess Days`, `Total Demand`, `Replenishment Units`.
- **Non-additive but defined** (averages / weighted): `Service Level`, `Fill Rate`, `Avg Days of Inventory`, `Avg Inventory Position`, `WMAE/WRMSE`, `Weighted Price`.
- **Keys:** `dim_product.product_surr_id`, `dim_store.store_surr_id`, `dim_date.date_id`, `scenario.scenario_id`, `fact_scenario_run.scenario_run_id`, `model_registry.model_id`.
- **Provenance column** `data_provenance` on every fact is exposed so a visual can assert/hide simulated content.
- Every measure definition carried in the metric layer (or SQL view) must reconcile additively where labeled additive (e.g., `Total Stockout Units` sums across any product/store subset by construction).

---

## 6. Required Calculated Measures

Metric-layer (or DAX) definitions — each with exactly one definition:

1. **Total Revenue** = `SUM(units × sell_price)` [mv_weekly_sales]
2. **Total Units** = `SUM(units_sold)` [observed]
3. **Revenue WoW/QoQ/YoY %** = `(cur/prior − 1)×100`, NULL/“—” when denominator ≤0 or absent
4. **Units WoW/QoQ/YoY %** = same on units
5. **Weighted Price** = `revenue/units` (NULL if units=0)
6. **Product/Category/Dept/Store/State Revenue Share %** = `entity_revenue/total_revenue×100`; cumulative for Pareto
7. **Total Stockout Days** = `SUM(stockout_days)`
8. **Total Stockout Units** = `SUM(stockout_units)`
9. **Total Excess Days** = `SUM(excess_days)`
10. **Total Excess Units** = `SUM(total_excess_units)`
11. **Total Demand** = `SUM(total_demand)`
12. **Replenishment Units** = `SUM(replenishment_units)`
13. **Avg Service Level** = demand-weighted `AVG(service_level_achieved)` (weight `total_demand`)
14. **Fill Rate** = `1 − total_stockout_units/total_demand` (Σ-level) or weighted avg
15. **Avg Days of Inventory** = `AVG(avg_days_of_inventory)` (non-additive)
16. **Avg Inventory Position** = `AVG(avg_inventory_position)` (non-additive)
17. **CM Case (WMAE)** = demand-weighted `Σ(w·|f−a|)/Σw`
18. **WRMSE** = demand-weighted sqrt `Σ(w·e²)/Σw`
19. **Bias** = `mean(f − a)` (positive = over-forecast)
20. **Stockout Risk Score / Tier / Rank** = passthrough from risk-run rows
21. **Excess Risk Score / Tier / Rank** = passthrough from excess-risk-run rows
22. **Scenario Delta (each metric)** = `scenario_value − baseline_value` (e.g., `ΔStockoutUnits`, `ΔServiceLevel`) from `delta_*` columns
23. **Series at Risk Count** = `COUNT` where `risk_tier IN (High, Critical)`
24. **Fill/Service Gap** = `target_service_level − achieved_service_level` (≥0)
25. **Provenance Label** = CASE over `data_provenance`

Weights for demand-weighted measures use `total_demand` (or `total_units_hist` where demand-weighted accuracy is required, matching phase-3D). All non-additive measures are explicitly non-additive in the semantic model.

---

## 7. Visual Specifications (per page)

> Scope: This page lists the chart/visual units each page presents (number, type, key axes, and which KPI feeds them). Exact theme/style is the build step's concern.

### P1 Executive Overview
- 4 KPI cards: Revenue, Units, Revenue WoW%, Units WoW% (with QoQ/YoY toggle)
- Revenue & Units line/area by week (`v_growth_wow`/`v_rollup_weekly`)
- Revenue by department (bar), by category (donut), by state (map/bar)
- Product Pareto (Top-N bar + cumulative line, `v_product_contribution`)
- Weighted price trend (line)
- Inventory snapshot cards: Avg Days-of-Inventory, Avg Service Level, Series at stockout/excess risk
### P2 Demand Overview
- Trend direction distribution (bar: increasing/flat/decreasing)
- CV distribution (histogram/box), attributable to volatility class
- Volume×Volatility risk matrix (heatmap of series counts)
- Demand pattern split (bar)
- Seasonality: peak/trough month, strength (by category/department), seasonal index line
- Day-of-week factor profile (scope-wide + by scope filter)
### P3 Forecast Performance
- Accuracy cards: WMAE, WRMSE, MAE, RMSE, Bias
- WMAE by dept/category (bar), by store (bar), by model family (bar vs selection)
- Model selection distribution (pie/bar of `is_selected`)
- Bias heatmap (by dept×store) — over/under trends
- Forecast vs actual: selected-series line with point/interval band (final 28-day)
### P4 Inventory Risk
- Inventory position / on-hand vs day (line, selected series or aggregate)
- Days-of-inventory distribution (histogram) + by category
- Service level achieved vs target (gauge/scatter) per series
- Safety stock & reorder point (scatter)
- Excess exposure: total excess units by category (bar) + by store
### P5 Stockout & Excess Risk
- Risk score distribution (histogram) per type
- Tier donut: series count by tier (each risk type)
- Top-N risk table (ranked list: series, score, tier, evidence) — the primary artifact
- Risk components breakdown (stacked, from `risk_components`)
- Map/rank strip of top series by store/state
### P6 Scenario Comparison
- Scenario selector → compare each scenario vs baseline
- Delta bars: ΔExcessDays, ΔStockoutUnits, ΔServiceLevel, ΔFillRate (per scenario)
- Per-scenario totals cards (total stockout/excess/demand)
- Service level & fill rate line by scenario
- Risk-tier shift matrix (baseline vs perturbed scenario tier transitions for the 2 rank scenarios)
### P7 Prioritized Operational Insights
- Prioritized table/list ranked by risk (evidence + op-note) with tier/score columns
- Side panel: evidence for selected series (stockout/excess/service)
- Filters: tier, dept, store, threshold, sort key
- Print/export action for the action-priority list

---

## 8. Acceptance Criteria

Each criterion is a checkable acceptance test the build step must satisfy before Phase 5 is considered complete. The dashboard must be implemented **faithful to the spec and the locked data** — not a restyle of invented metrics.

**Data correctness:**
1. Every revenue/units figure reconciles to `v_weekly`/`v_revenue` and matches phase-3B observed totals (units reconcile to `66,927,173`; revenue to the stored anchor).
2. Forecast accuracy measures on P3 equal `fact_forecast_evaluation` values for the same series and model (WMAE/WRMSE/bias).
3. Scenario totals on P6 equal GROUP BY of `fact_scenario_result` (30,490 rows × N scenarios) and sum to 213,430.
4. Risk tiers/scores/ranks on P5 equal the rank-run rows; rank is 1..30,490 with no ties.
5. Simulated/driving KPI cards that show mean service level or days-of-inventory match the baseline scenario run's aggregate.
6. No measure on any page reads `fact_daily_sales` directly except the explicitly bounded `v_rollup_daily` sparklines, and those only under date/product/store filters.

**Model/dashboard structure:**
7. Data contract §5 grain/keys are implemented; relationships conformed via dims (product/store/date/scenario/model).
8. Non-additive measures are declared non-additive; additive measures sum correctly across any subset.
9. Provenance is exposed and rendered (label or filter) on every simulated visual.
10. Filters in §4 are available; cross-filtering works between all pages; drill paths work (state→store, dept→category→product, period→week→day).

**Business/UX:**
11. The 7 pages are present, in the §1 order and intent.
12. Each KPI in §2 is present with the §7 visual type, labeled with its definition/tooltip.
13. P7 surfaces ranked evidence with qualitative op-notes and does **not** present a decision/recommendation engine output (that remains deferred).
14. Page 6 shows 4 scenario comparisons (demand shock, lead-time, service-level, reorder policy) against baseline, with deltas; `fact_scenario_comparison` (currently 0 rows) may render a "no comparison rows yet" state rather than fabricated values.
15. Empty/undefined values (unpriced revenue, zero-denominator growth) render as "—", never fabricated.

**Performance:**
16. No unbounded full-table scan occurs on load; P1–P7 default queries operate on ≤ ~214K scenario rows / ~8.5M weekly rows / bounded slices, and page-level filters precede any daily-grain access.
17. Time-to-interactive for each page is acceptable (bounded surfaces, materialized views); no 59M-row scan.

**Traceability/acceptance artifact:** the dashboard model includes a documented mapping (spec §3 table) from every visual/KPI back to its locked source table+column, so `reports/PHASE_5_DASHBOARD_SPEC.md` (this doc) serves as the contract the build/test verify against.

---

## 9. Out of Scope (explicitly deferred)

- Building the Power BI model, DAX/visual layer, or web application (build step, later).
- `fact_replenishment_recommendation` population and any decision-recommendation engine output (Phase 4 decision-engine step).
- Any new forecasting models, inventory sizing, or scenario definitions.
- Recomputing the 59M-row observed fact.
- Modifying any Phase 1–4 object or data.