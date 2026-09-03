# Power BI Semantic Data Model — Phase 5 Step 1 (Specification & Build Contract)

**Status:** Step 1 (semantic model + measures) implemented as an executable spec.
`reports/PHASE_5_DASHBOARD_SPEC.md` is the governing business contract; this document is the
**model implementation contract** a Power BI Desktop author follows to build the `.pbit`, and it is
enforced programmatically by `tests/dashboard/test_semantic_model.py`.

**Locked inputs:** Phases 1–4 verified production data (scenario engine run_id=11 success). All
figures below are real, verified query results — not invented.

---

## 1. Model Design Decisions (read this first)

1. **Star schema over locked derived surfaces.** No table re-queries `fact_daily_sales`. The only
   daily-grain fact exposed is `DimDate` (calendar) and the bounded daily series used by visuals only under
   mandatorily-applied filters — it is **not** a model table.
2. **Imported (in-memory) tables.** All facts are small enough to Import (max 8.5M weekly rows;
   scenario/forecast/inventory ~0.85–0.21M rows). **Import mode** is required so that non-additive,
   deterministically defined measures evaluate exactly and so provenance/risk-rank logic is auditable.
3. **Conformed dimensions are single physical tables**, referenced by every fact (shared key columns),
   guaranteeing **one-to-many** relationships from dim → fact only.
4. **Models 1–4 vs 5–6 split (evaluation).** `fact_forecast_evaluation` is **the locked reality**:
   models 1–4 (naive, seasonal_naive, moving_average, weighted_ma) are evaluated on all 30,490 series;
   models 5–6 (ets_holt_winters, sarima) ONLY on the 64-series pilot. This is a documented grain nuance,
   not an error: any "overall accuracy" visual/in measure that crosses a model ask **must** restrict to the
   common pilot (64 series) or be labeled as per-model-with-varying-support. The reusable model exposes
   the exact per-series×model rows (122,088) — never fabricates full support for of ETS/SARIMA.
5. **Final forecast** (`fact_forecast WHERE is_final`) = **exactly one model per (series, date)** —
   verified: 853,720 distinct (series, day) = 30,490 × 28, `MULTI_MODEL=0`. Joining `Model` by `model_id`
   is a **1:1 (no fan-out)** enrichment. Model selection display uses `Model.is_selected` (naive id=1).
6. **Provenance** is a first-class attribute on every fact and the `DimScenario`/`DimForecast` context:
   simulated visuals are labeled. Provenance is *not* a relationship driver.

---

## 2. Tables (tables, grain, keys, columns to import)

> Naming: `Dim*` = dimension (conformed), `Fact*` = fact (grain/measure-bearing). Power Query steps
> are described; only listed columns are imported (avoid calculated columns — fold/pull the fields
> already stored).

### 2.1 Dimensions

**DimProduct** — source `dim_product`
- Grain: product; PK `product_surr_id` (`INT`, unique, `biol`).
- Imported: `product_surr_id` (key), `product_id`, `item_id`, `dept_id`, `dept_surr_id`,
  `category_id`, `category_surr_id`, `product_label`.
- Rows: 3,049.

**DimCategory** — source `dim_category`
- Grain: category; PK `category_surr_id`.
- Imported: `category_surr_id`, `category_id`, `category_name`. Rows: 3.

**DimDepartment** — source `dim_department`
- Grain: department; PK `dept_surr_id`.
- Imported: `dept_surr_id`, `dept_id`, `dept_name`, `category_id`, `category_surr_id`. Rows: 7.
- Note: `DimDepartment.category_surr_id` is a **role-playing** link to `DimCategory` (one dimension),
  usable for a department→category drill path; it is not a separate relationship.

**DimStore** — source `dim_store`
- Grain: store; PK `store_surr_id`.
- Imported: `store_surr_id`, `store_id`, `state_id`, `region_id`, `store_name`. Rows: 10.
- `state_id` (CA/TX/WI) and `region_id` are **text attributes inside DimStore** (hierarchy, not separate
  dims) to keep the grain conformed; a `DimState` is not created (10 stores, 3 states → attribute suffices).

**DimDate** — source `dim_date`
- Grain: day; PK `date_id` (`INT`). Rows: 1,969 (observed 1,941 + 28 forecast horizon; `is_observed` flag).
- Imported: `date_id` (key), `calendar_date`, `day_index`, `wm_yr_wk`, `week_id`, `weekday_num`,
  `weekday_name`, `is_weekend`, `month`, `month_name`, `quarter`, `year`, `is_event_day`,
  `event_name_1`, `event_type_1`, `is_observed`.
- Hierarchy (reporting-level role plays): `year → quarter → month → date_id` and week attributes
  (`wm_yr_wk`, `week_id`).

**DimScenario** — source `scenario`
- Grain: scenario definition; PK `scenario_id`.
- Imported: `scenario_id`, `scenario_name`, `scenario_type`, `params_json` (as text for display),
  `base_assumption_set_id`, `description`, `is_active`. Rows: 7.
- `params_json` used only as descriptive text (never parsed into model columns).

**DimScenarioRun** — source `fact_scenario_run`
- Grain: scenario run; PK `scenario_run_id`.
- Imported: `scenario_run_id`, `scenario_id`, `assumption_set_id`, `executed_at`, `status`,
  `records_processed`, `data_provenance`. Rows: 7.
- **Relationships:** `DimScenarioRun[scenario_id] → DimScenario[scenario_id]`
  (many runs to one definition). Status/executed provenance surfaced for traceability.

**DimModel** — source `model_registry`
- Grain: model; PK `model_id`.
- Imported: `model_id`, `model_name`, `model_family`, `params_json` (text), `training_window`,
  `validation_method`, `is_selected`, `metrics_json` (text), `git_ref`. Rows: 6.
  (`model_name`={naive, seasonal_naive, moving_average, weighted_ma, ets_holt_winters, sarima};
  `is_selected`=naive.)

**DimAssumptionSet** — source `assumption_set`
- Grain: assumption set; PK `assumption_set_id`.
- Imported: `assumption_set_id`, `name`, `supplier_lead_time_days`, `service_level`,
  `safety_stock_formula`, `reorder_policy`, `reorder_quantity_rule`, `demand_adjustment`, `is_active`.
  Rows: 1 (id=1, the Phase 3E baseline).

### 2.2 Facts

**FactScenarioResult** — source `fact_scenario_result` (ROW = 213,430, **grain = `(scenario_run_id, product_surr_id, store_surr_id)`**)
- Imported key/relationships columns: `scenario_run_id`, `product_surr_id`, `store_surr_id`, `data_provenance`.
- Imported measure-bearing columns: `expected_daily_demand`, `daily_sigma`, `cv`, `total_units_hist`,
  `safety_stock`, `reorder_point`, `reorder_qty`, `starting_inventory`, `lead_time_days`,
  `service_level_target`, `total_demand`, `stockout_days`, `stockout_units`, `service_level_achieved`,
  `fill_rate`, `reorder_frequency`, `total_reorder_units`, `replenishment_units`, `avg_inventory_position`,
  `avg_on_hand`, `final_on_hand`, `final_on_order`, `final_backorder`, `excess_days`, `total_excess_units`,
  `avg_days_of_inventory`, `risk_score`, `risk_tier`, `risk_rank`, `risk_components` (jsonb→text),
  `delta_stockout_days`, `delta_stockout_units`, `delta_service_level`, `delta_fill_rate`,
  `delta_reorder_frequency`, `delta_total_reorder_units`, `delta_avg_inventory_position`,
  `delta_excess_days`, `delta_total_excess_units`, `delta_avg_days_of_inventory`.
- **This is the central scenario fact.** Baseline run + 2 risk-rank runs carry the risk fields and deltas;
  ranking/insight visuals read this table (see `risk_tier`/`risk_rank` integrity below).

**FactScenarioComparison** — source `fact_scenario_comparison`
- Grain: `(scenario_run_id, baseline_scenario_run_id)`; PK `comparison_id`.
- Imported: `comparison_id`, `scenario_run_id`, `baseline_scenario_run_id`, `aggregate_json` (text),
  `n_series`, `horizon_days`, `data_provenance`.**Current rows: 0** (no `action_tradeoff` scenario in
  the 7-production-scenario set). The table is **modeled and available**, but the comparison page shows
  an explicit "no comparison rows yet" empty state (spec acceptance 14). Relationships defined for when
  data arrives.

**FactInventorySimulation** — source `fact_inventory_simulation` (853,720 rows, **grain = `(product_surr_id, store_surr_id, day_id)`**)
- Imported: `product_surr_id`, `store_surr_id`, `day_id`, `assumption_set_id`, `starting_inventory`,
  `demand_forecast`, `lead_time_demand`, `safety_stock`, `reorder_point`, `inventory_position`,
  `on_hand`, `orders_placed`, `reorder_qty`, `projected_stockout`, `stockout_units`, `excess_inventory`,
  `days_of_inventory`, `service_level_achieved`, `data_provenance`.
- Day grain is **28-day forecast horizon (date_id 1942..1969)**, not the full M5 1,941-day historical span.

**FactForecast** — source `fact_forecast` (final only; 853,720 rows, **grain = `(product_surr_id, store_surr_id, forecast_date)`**, single `forecast_origin`)
- Import: filter `is_final = TRUE`. Imported: `product_surr_id`, `store_surr_id`, `model_id`,
  `forecast_origin`, `forecast_horizon`, `forecast_date`, `forecast_value`, `lower_bound`, `upper_bound`,
  `data_provenance`.
- Join to `DimModel[model_id]` is **1:1 per (series,date)** (verified, no fan-out). Join to
  `DimDate[date_id]` on `forecast_date`.

**FactForecastEvaluation** — source `fact_forecast_evaluation` (122,088 rows)
- Grain: **`(product_surr_id, store_surr_id, model_id)`** where the model was evaluated.
- Imported: `product_surr_id`, `store_surr_id`, `model_id`, `validation_start`, `validation_end`,
  `mae`, `rmse`, `wmae`, `wrmse`, `abs_error`, `bias`, `n_holdout`, `data_provenance`.
- **Support nuance (locked):** models 1–4 → all 30,490 series; models 5–6 → 64 series (pilot). See §1.4.

**FactDemandAnalysis** — source `fact_demand_analysis` (30,490 rows, **grain = `(product_surr_id, store_surr_id, analysis_window)`**)
- Imported: `product_surr_id`, `store_surr_id`, `analysis_window`, `total_units`, `mean_daily_units`,
  `std_daily_units`, `cv`, `zero_demand_days`, `zero_demand_ratio`, `avg_week_units`, `recent_4wk_mean`,
  `prior_4wk_mean`, `demand_growth_rate`, `growth_is_defined`, `growth_denominator_zero`, `trend_slope`,
  `trend_effect_pct`, `trend_direction`, `seasonality_strength`, `has_meaningful_seasonality`,
  `peak_month`, `trough_month`, `n_active_months`, `segment_volume`, `segment_volatility`,
  `segment_demand`, `risk_cell`, `risk_category`, `data_provenance`.

**FactProductStoreDemand** — source `fact_product_store_demand` (30,490) — the Phase-3B demand layer
  (subset of the above with base stats). Import if the dashboard needs the canonical Phase-3B layer;
  otherwise **fold/pull `FactDemandAnalysis` only** (both verified, choose one to avoid duplication).
  Model chooses **`FactDemandAnalysis`** as the single demand fact.

**FactDemandSeasonality** — source `fact_demand_seasonality` (359,181 rows, grain `(product_surr_id, store_surr_id, month[, analysis_window])`)
- Imported: `product_surr_id`, `store_surr_id`, `analysis_window`, `month`, `seasonality_index`,
  `obs_weeks`, `is_meaningful`, `data_provenance`.

**FactDemandSeasonalityDow** — source `fact_demand_seasonality_dow`
- Grain: `(scope_type, scope_key, scope_value, weekday_num)`; NOT product-store-granular (aggregate scope factor).
- Imported: `scope_type`, `scope_key`, `scope_value`, `weekday_num`, `weekday_name`, `dow_index`,
  `obs_days`, `data_provenance`.
- This is an **aggregate/shared table**; it joins to `DimDate[weekday_num]` and is filtered by scope
  attributes (all / category / dept / store / state). It is **not** a per-series fact.

**FactWeeklySales** — source `mv_weekly_sales` (8,476,220 rows, **grain = `(product_surr_id, store_surr_id, wm_yr_wk)`**)
- Imported: `product_surr_id`, `store_surr_id`, `wm_yr_wk`, `units`, `sell_price`, `revenue`.
- Weight ≈ 8.5M rows — largest import; acceptable for Import mode (single pass over the already-materialized
  weekly anchor, ~a few hundred MB). **No `fact_daily_sales` query.** This backs Revenue/Units/Pareto/growth.
- Join to `DimDate` is by week (`wm_yr_wk`) via a **role-playing week** relationship (a `DimForecast`-like
  week table OR reusing `DimDate` filtered to week rows). To keep one `DimDate`, model an explicit
  `DimForecast`-free approach: `FactWeeklySales[wm_yr_wk] → DimDate[wm_yr_wk]` (many rows per dim-day)
  — document as a 1:* but usable for weekly grain; alternatively add a small `DimWeek`.

**Decision (week vs day):** Add a **`DimWeek`** table (grain week, PK `wm_yr_wk`, created from
`SELECT DISTINCT wm_yr_wk, week_id, year, quarter, month FROM dim_date`) so `FactWeeklySales` relates
conformedly at its true grain (avoiding a fan-out/redundant day relationship). `DimDate` remains the
day-level calendar. This keeps 1:* in the correct grain.
- **Cardinality nuance (verified):** `dim_date` has **282** distinct `wm_yr_wk` (full M5 282-week calendar);
  `mv_weekly_sales` covers **278** of them (the trade calendar in which these series were active). A `DimWeek`
  DIMMED from `dim_date` therefore has 282 rows and is **filter-dimension-only** (a slicer over 282 weeks);
  the `FactWeeklySales` fact relates on the 278 weeks present. A visual that slices a week with no sales
  shows an empty chart (correct, not fabricated) — matching spec §8b.

---

## 3. Relationships (conformed, explicit)

| From (many) | To (one) | Cardinality | Cross-filter | Active | Key |
|---|---|---|---|---|---|
| FactWeeklySales | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactWeeklySales | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactWeeklySales | DimWeek | Many-to-One | Single | yes | wm_yr_wk |
| FactDemandAnalysis | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactDemandAnalysis | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactDemandSeasonality | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactDemandSeasonality | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactDemandSeasonality | DimDate | Many-to-One | Single | yes | month (role: datetime) |
| FactDemandSeasonalityDow | DimDate | Many-to-One | Single | yes | weekday_num (role) |
| FactForecast | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactForecast | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactForecast | DimModel | Many-to-One | Single | yes | model_id (1:1 enrichment) |
| FactForecast | DimDate | Many-to-One | Single | yes | forecast_date (→ date_id) |
| FactForecastEvaluation | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactForecastEvaluation | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactForecastEvaluation | DimModel | Many-to-One | Single | yes | model_id |
| FactInventorySimulation | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactInventorySimulation | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactInventorySimulation | DimDate | Many-to-One | Single | yes | day_id (→ date_id) |
| FactInventorySimulation | DimAssumptionSet | Many-to-One | Single | yes | assumption_set_id |
| FactScenarioResult | DimScenarioRun | Many-to-One | Single | yes | scenario_run_id |
| FactScenarioResult | DimProduct | Many-to-One | Single | yes | product_surr_id |
| FactScenarioResult | DimStore | Many-to-One | Single | yes | store_surr_id |
| FactScenarioResult | DimScenario (via run) | Many-to-One | Single | yes | (indirect) |
| DimScenarioRun | DimScenario | Many-to-One | Single | yes | scenario_id |
| DimScenarioRun | DimAssumptionSet | Many-to-One | Single | yes | assumption_set_id |
| FactScenarioComparison | DimScenarioRun (scenario_run_id) | Many-to-One | Single | yes | scenario_run_id |
| FactScenarioComparison | DimScenarioRun (baseline) | Many-to-One | Single | inactive | baseline_scenario_run_id |

**Rules**
- All relationships are **one direction (Single)**; **no Bi-directional** unless a measure explicitly needs
  it, to avoid ambiguity. The scenario facts rely on `DimScenarioRun → DimScenario` for scenario-name slicing.
- `DimDepartment` and `DimCategory` are related via a **single direction** relationship
  (`DimDepartment[category_surr_id] → DimCategory[category_surr_id]`) so a product→dept→category drill works;
  `DimProduct` also links to both for filtering.
- No table-to-table relationship crosses `fact_daily_sales`; weekly/growth visuals use `FactWeeklySales`.
- Every imported fact exposes `data_provenance`; provenance is rendered via measures, never a relationship.

---

## 4. Storage / Performance Safeguards

1. **Import mode**, not DirectQuery. All facts are bounded small tables; no live 59M scans.
2. `FactWeeklySales` is the largest (8.5M) — import once from the materialized weekly anchor; drop
   unused columns (`sell_price`/`revenue` kept; no derived daily columns).
3. **No calculated columns** that simply recompute stored columns (e.g., `RiskTier` is already a column;
   `params_json` is stored as text). Use **measures** (CALCULATE/SUMX) instead (spec §3).
4. **Bounded day access:** no `fact_daily_sales` table is imported. Any daily-grain visual is
   **not** part of the model; if a future page needs a daily sparkline it must bind to `DimDate`+ the
   28-day forecast/inventory facts (already only 28 days) — never the 59M observed fact.
5. **In-model row reduction:** `FactForecast` imported **filtered to `is_final=TRUE`** only. `FactScenarioResult`
   is the scenario fact (213K). `FactForecastEvaluation` supports the per-model evaluation nuance.
6. **Optimize columns:** numeric columns imported as-is; `risk_components`, `params_json`, `aggregate_json`,
   `metrics_json` imported as text (not expanded) to avoid schema blow-up.
7. **Period/time grains:** week-level time on `DimWeek`, day-level on `DimDate`; a single `Harvest`/`Maybe`
   not required. Use `JOIN` keys only; no cross-filters on time are set active unless the grain fits
   (weekly facts) vs day facts.

---

## 5. Provenance Contract (verified against the locked DB)

- Every fact carries `data_provenance` ∈ {observed, derived, simulated}.
- **Verified provenance by surface:**
  | Surface | Provenance |
  |---|---|
  | `fact_forecast` (final), `fact_forecast_evaluation` | **derived** |
  | `fact_demand_analysis`, `fact_product_store_demand` | **derived** |
  | `fact_demand_seasonality`, `fact_demand_seasonality_dow` | **derived** |
  | `fact_inventory_simulation` | **simulated** |
  | `fact_scenario_result`, `fact_scenario_run`, `scenario` | **simulated** |
  | `fact_daily_sales` (observed anchor; not a model table) | observed |
- **Correction note:** forecasts are **derived**, not simulated — they are computed end-to-end from
  observed demand. Only scenario outputs and the inventory simulation are simulated. Page 3 (forecast)
  must render provenance as **derived**; P4/P5/P6/P7 as **simulated**.
- Model exposes a `Provenance Label` measure so each page flags the correct provenance. No visual consumes
  a simulated/derived number as observed.
- Traceability document (`docs/phase5_traceability.md`) records the provenance of each KPI source.

---

## 6. Model Acceptance (encoded in `tests/dashboard/test_semantic_model.py`)

The executable harness validates this document's facts against the locked DB:
- model table inventory & grains (row counts as listed),
- key uniqueness (PK uniqueness per dim),
- relationship key type parity,
- reconciliation (units=66,927,173; scenario=213,430; forecast=853,720=30,490×28; inventory=853,720, right date span),
- evaluation grain & per-model support (122,088; models1–4 all series, 5–6 pilot 64),
- risk-rank integrity (1..30,490 unique per rank run),
- provenance (all scenario simulated),
- measure-definition table round-trip (additive vs non-additive flags).