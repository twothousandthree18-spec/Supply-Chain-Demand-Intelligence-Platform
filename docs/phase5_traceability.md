# Phase 5 — Dashboard Traceability Matrix

**Phase 5 Step 1 (semantic model).** This document maps **every dashboard KPI / required measure** to
the **exact locked source table/view + column** and its **business definition**. It is the single
source of truth for what the dashboard shows and where each number came from — jointly governed by
`reports/PHASE_5_DASHBOARD_SPEC.md` (business spec) and `dashboards/powerbi/POWERBI_MODEL.md` (model contract).

**Provenance legend:** `obs` = observed, `der` = derived, `sim` = simulated (verified against the DB; see
`tests/dashboard/test_semantic_model.py::test_provenance_contract_all_surfaces`).

---

## A. Revenue / Commercial

| KPI / Measure | Definition | Source table | Source column(s) | Provenance | Additive |
|---|---|---|---|---|---|
| Total Revenue | `SUM(units × sell_price)` at any grain | `mv_weekly_sales` (`v_revenue`) | `units × sell_price` | der | yes |
| Total Units | `SUM(units_sold)` | `mv_weekly_sales` (`v_units`) | `units` | der | yes |
| Weighted Price | `revenue / units` (BLANK when units=0) | `mv_weekly_sales` (`v_price_weekly`) | `revenue`, `units` | der | no |
| Revenue WoW % | `(cur_wk/prev_wk − 1)×100` | `mv_weekly_sales` + `DimWeek` (`v_growth_wow`) | `wm_yr_wk`, `revenue` | der | no |
| Units WoW % | `(cur_wk/prev_wk − 1)×100` | `mv_weekly_sales` + `DimWeek` (`v_growth_wow`) | `wm_yr_wk`, `units` | der | no |
| Revenue QoQ % | quarter-over-quarter % | `mv_weekly_sales` (`v_growth_qoq`) | `year`, `quarter`, `revenue` | der | no |
| Revenue YoY % | year-over-year % | `mv_weekly_sales` (`v_growth_yoy`) | `year`, `revenue` | der | no |
| Units YoY % | year-over-year % | `mv_weekly_sales` (`v_growth_yoy`) | `year`, `units` | der | no |
| Entity Revenue Share % | `entity_revenue/total×100` (per product/dt/category/store/state) | `v_product_contribution`, `v_department_contribution`, `v_category_contribution`, `v_store_contribution`, `v_state_contribution` | `revenue`, `revenue_share_pct` | der | no |
| Product Revenue Share % | within product share | `v_product_contribution` | `revenue`, `revenue_share_pct` | der | no |
| Cumulative Product Revenue Share % | running SUM share (Pareto) | `v_product_contribution` | `cumulative_share_pct` | der | no |

**Grain/keys:** `(product_surr_id, store_surr_id, wm_yr_wk)`; dims `DimProduct`, `DimStore`, `DimWeek`.
Reconciliation: `Σ mv_weekly_sales.units = 66,927,173` = observed total.

---

## B. Demand Analysis & Seasonality

| KPI / Measure | Definition | Source table | Source column(s) | Provenance | Additive |
|---|---|---|---|---|---|
| Demand trend direction | increasing/flat/decreasing | `fact_demand_analysis` | `trend_direction`, `trend_effect_pct`, `trend_slope` | der | no |
| Demand growth rate | `recent_4wk/prior_4wk − 1` (BLANK when zero base) | `fact_demand_analysis` | `demand_growth_rate`, `growth_is_defined`, `growth_denominator_zero` | der | no |
| Volatility (CV) | `std_daily_units/mean` | `fact_demand_analysis` | `cv`, `mean_daily_units`, `std_daily_units` | der | no |
| Volume tercile | Low/Medium/High | `fact_demand_analysis` | `segment_volume` | der | no |
| Volatility class | Low/Medium/High | `fact_demand_analysis` | `segment_volatility` | der | no |
| Demand pattern | Smooth/Erratic/Lumpy/Intermittent | `fact_demand_analysis` | `segment_demand`, `zero_demand_ratio` | der | no |
| Risk matrix cell/category | volume×volatility cell + risk category | `fact_demand_analysis` | `risk_cell`, `risk_category` | der | no |
| Seasonality strength | CV of seasonal indices | `fact_demand_analysis` | `seasonality_strength`, `has_meaningful_seasonality` | der | no |
| Peak/trough month | max/min monthly index | `fact_demand_seasonality` | `month`, `seasonality_index`, `is_meaningful` | der | no |
| Day-of-week factors | scope-level DOW indices | `fact_demand_seasonality_dow` | `weekday_num`, `dow_index`, `scope_type`, `scope_value` | der | no |
| Demand layer stats (canonical) | total/mean/std/cv/growth/trend | `fact_product_store_demand` | `total_units`, `mean_daily_units`, `cv`, `demand_growth_rate`, `trend_slope` | der | no |

**Grain/key:** `(product_surr_id, store_surr_id, analysis_window)`; DOW table grain `(scope_type, scope_key,
scope_value, weekday_num)`; seasonality `(product_surr_id, store_surr_id, month)`.

---

## C. Forecasting

| KPI / Measure | Definition | Source table | Source column(s) | Provenance | Additive |
|---|---|---|---|---|---|
| Forecast MAE | mean absolute error | `fact_forecast_evaluation` | `mae`, `model_id` | der | no |
| Forecast RMSE | root mean squared error | `fact_forecast_evaluation` | `rmse` | der | no |
| Forecast WMAE | demand-weighted MAE | `fact_forecast_evaluation` × `fact_demand_analysis.total_units` | `wmae`, weight `total_units` | der | no |
| Forecast WRMSE | demand-weighted RMSE | `fact_forecast_evaluation` × `fact_demand_analysis.total_units` | `wrmse`, weight `total_units` | der | no |
| Forecast Bias | `mean(f−a)`, + = over-forecast | `fact_forecast_evaluation` | `bias` | der | no |
| Model selection | which model is selected per series | `model_registry` | `is_selected`, `model_name`, `model_family` | der | no |
| Final forecast (value/interval) | point + lower/upper | `fact_forecast` (is_final) | `forecast_value`, `lower_bound`, `upper_bound`, `forecast_date` | der | no |
| Forecast volume (period) | `SUM(forecast_value)` | `fact_forecast` (is_final) | `forecast_value` | der | no |
| Evaluation support | rows per model (models1-4=all series, 5-6=pilot 64) | `fact_forecast_evaluation` | `model_id`, `n_holdout` | der | no |

**Grain/key:**
- `fact_forecast` final: `(product_surr_id, store_surr_id, forecast_date)` = 30,490 × 28 = **853,720**;
  one `model_id` per (series,date) → no fan-out; dates **1942..1969**.
- `fact_forecast_evaluation`: `(product_surr_id, store_surr_id, model_id)` per evaluated model = **122,088**;
  models 1–4 eval all 30,490; models 5–6 (ETS/SARIMA) eval the 64-series pilot only (locked limitation).
- `model_registry`: 6 models, `is_selected = naive`.

**Power BI limitation (documented):** evaluation-support is not constant across models, so a cross-model
aggregate ("overall WMAE") is only valid on the **common pilot (64 series)**; otherwise it must be presented
per-model with its own support. The model does not fabricate full-model support.

---

## D. Inventory & Scenario

| KPI / Measure | Definition | Source table | Source column(s) | Provenance | Additive |
|---|---|---|---|---|---|
| Inventory position (time) | `inventory_position` per day | `fact_inventory_simulation` | `inventory_position`, `day_id` | sim | no |
| On-hand / on-order / backorder | `on_hand`, `orders_placed`, `projected_stockout` | `fact_inventory_simulation` | `on_hand`, `orders_placed`, `projected_stockout`, `stockout_units` | sim | no |
| Days of inventory | per-day days-of-inventory | `fact_inventory_simulation` | `days_of_inventory` | sim | no |
| Service level (achieved) | per-day achieved | `fact_inventory_simulation` | `service_level_achieved` | sim | no |
| Safety stock / reorder point | policy snapshot | `fact_scenario_result` (baseline run) | `safety_stock`, `reorder_point` | sim | no |
| Total Stockout Days | `SUM(stockout_days)` | `fact_scenario_result` | `stockout_days` | sim | yes |
| Total Stockout Units | `SUM(stockout_units)` | `fact_scenario_result` | `stockout_units` | sim | yes |
| Total Excess Days | `SUM(excess_days)` | `fact_scenario_result` | `excess_days` | sim | yes |
| Total Excess Units | `SUM(total_excess_units)` | `fact_scenario_result` | `total_excess_units` | sim | yes |
| Total Demand | `SUM(total_demand)` | `fact_scenario_result` | `total_demand` | sim | yes |
| Replenishment Units | `SUM(replenishment_units)` | `fact_scenario_result` | `replenishment_units` | sim | yes |
| Avg Service Level | demand-weighted mean | `fact_scenario_result` | `service_level_achieved`, weight `total_demand` | sim | no |
| Fill Rate | `1 − stockout_units/demand` | `fact_scenario_result` | `stockout_units`, `total_demand` | sim | no |
| Avg Days of Inventory | `AVG(avg_days_of_inventory)` | `fact_scenario_result` | `avg_days_of_inventory` | sim | no |
| Avg Inventory Position | `AVG(avg_inventory_position)` | `fact_scenario_result` | `avg_inventory_position` | sim | no |
| Fill/Service Gap | `target − achieved` (≥0) | `fact_scenario_result` × `assumption_set` | `service_level_achieved`, `service_level_target`, `assumption_set.service_level` | sim | no |

**Grain/keys:**
- `fact_inventory_simulation`: `(product_surr_id, store_surr_id, day_id=1942..1969)` = 30,490 × 28 = **853,720** (sim).
- `fact_scenario_result`: `(scenario_run_id, product_surr_id, store_surr_id)` = **213,430** rows, all sim.

---

## E. Risk Ranking & Scenario Deltas

| KPI / Measure | Definition | Source table | Source column(s) | Provenance | Additive |
|---|---|---|---|---|---|
| Stockout Risk Score | weighted 5-component score | `fact_scenario_result` (stockout rank run) | `risk_score` | sim | no |
| Stockout Risk Tier | Low/Medium/High/Critical | `fact_scenario_result` | `risk_tier` | sim | no |
| Stockout Risk Rank | 1..30,490 | `fact_scenario_result` | `risk_rank` | sim | no |
| Excess Risk Score / Rank | weighted 3-component ranking | `fact_scenario_result` (excess rank run) | `risk_score`, `risk_rank` | sim | no |
| Risk components | component breakdown | `fact_scenario_result` | `risk_components` (jsonb) | sim | no |
| Series at Risk Count | `COUNT` where tier High/Critical | `fact_scenario_result` | `risk_tier` | sim | no |
| Scenario Delta Stockout Units | `scenario − baseline` | `fact_scenario_result` | `delta_stockout_units` (or computed) | sim | no |
| Scenario Delta Service Level | `scenario − baseline` | `fact_scenario_result` | `delta_service_level` | sim | no |
| Scenario Delta Excess Days | `scenario − baseline` | `fact_scenario_result` | `delta_excess_days` | sim | no |
| Scenario Delta Fill Rate | `scenario − baseline` | `fact_scenario_result` | `delta_fill_rate` | sim | no |
| Scenario Delta Avg Inventory Position | `scenario − baseline` | `fact_scenario_result` | `delta_avg_inventory_position` | sim | no |
| Scenario run → definition | run id → name/type/params | `fact_scenario_run` × `scenario` | `scenario_run_id`, `scenario_id`, `scenario_name`, `scenario_type`, `params_json` | sim | — |
| Scenario comparison | aggregate comparison (0 rows today) | `fact_scenario_comparison` | `aggregate_json`, `n_series`, `horizon_days` | sim | no |

**Risk-rank integrity (verified):** each rank run has exactly 30,490 distinct `risk_rank` values = 1..30,490;
decided on `(scenario_run_id=6 stockout, =7 excess)`. **No ties.**

**Scenario definitions (run→name/type):**
| scenario_run_id | name | type |
|---|---|---|
| 1 | baseline | baseline |
| 2 | demand_shock_p20 | demand_shock |
| 3 | lead_time_plus_2d | lead_time_change |
| 4 | service_level_99 | service_level_change |
| 5 | reorder_policy_alt | reorder_policy |
| 6 | stockout_risk_rank | stockout_risk_prioritization |
| 7 | excess_risk_rank | excess_inventory_prioritization |

**Comparison note (locked):** the 7-scenario production set contains **no `action_tradeoff`** scenario, so
`fact_scenario_comparison` = **0 rows**. The comparison page renders an explicit empty state rather than
fabricated numbers (spec acceptance 14).

---

## F. Provenance Contract (verified)

| Surface | Provenance |
|---|---|
| `fact_forecast` (final), `fact_forecast_evaluation` | **derived** |
| `fact_demand_analysis`, `fact_product_store_demand` | **derived** |
| `fact_demand_seasonality`, `fact_demand_seasonality_dow` | **derived** |
| `fact_inventory_simulation` | **simulated** |
| `fact_scenario_result`, `fact_scenario_run`, `scenario` | **simulated** |
| `fact_daily_sales` (observed; not a model table) | observed |

Every visual that reads a `derived` or `simulated` metric renders its provenance label (measure
`Provenance Label`) so a number is never presented as observed when it is derived/simulated.

---

## G. Reconciliation Anchors (audited)

| Anchor | Value | Source check |
|---|---|---|
| Observed units | **66,927,173** | `SUM(mv_weekly_sales.units)` == `SUM(fact_daily_sales.units_sold WHERE observed)` |
| Scenario result rows | **213,430** | `COUNT(fact_scenario_result)` |
| Forecast final grain | **853,720** = 30,490 × 28 | `COUNT(fact_forecast WHERE is_final)` |
| Inventory grain | **853,720** = 30,490 × 28 (days 1942..1969) | `COUNT(fact_inventory_simulation)` |
| Evaluation grain | **122,088** (models1-4×30,490 + models5-6×64) | `COUNT(fact_forecast_evaluation)` |
| Calendar weeks / sales weeks | 282 / 278 | `COUNT(DISTINCT wm_yr_wk)` dim_date / mv_weekly_sales |
| Risk rank integrity | 1..30,490 unique per run | per-run distinct rank count |

Validated by `tests/dashboard/test_semantic_model.py` (19 checks).