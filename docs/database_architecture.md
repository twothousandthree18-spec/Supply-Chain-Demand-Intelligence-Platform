# Database Architecture (PostgreSQL)

**Phase 0 — Design only. The database has NOT been created or populated.**

---

## 1. Purpose

PostgreSQL is the single source of truth. It enforces referential integrity, stores the validated warehouse, is the foundation of the SQL analytical layer, and provides auditable KPI definitions.

## 2. Principles

- **Star/snowflake hybrid:** Central fact tables referencing conformed dimensions.
- **Typed & constrained:** Foreign keys, `NOT NULL`, `CHECK` constraints on codes, indexes on join/filter keys.
- **Versioned DDL:** All schema under `sql/ddl/`, reviewed and reproducible.
- **Auditable:** Every load recorded in `etl_run_log`; every quality check in `data_quality_results`.

## 3. Data Tripartition Mapping

To keep Observed / Derived / Simulated data structurally separate:

- **Observed** → source fact tables directly fed by ETL (e.g., `fact_daily_sales`, `fact_weekly_price`).
- **Derived** → analytical fact tables / views produced by analytics and forecasting (e.g., `fact_forecast`, `fact_forecast_evaluation`, demand statistics).
- **Simulated** → inventory/replenishment/hypothetical scenario tables (e.g., `fact_inventory_simulation`, `fact_replenishment_recommendation`), each carrying an explicit `assumption_set` of parameters.

Every row in any fact table that is derived or simulated carries a `data_provenance` marker (`observed` | `derived` | `simulated`) so labeling is enforceable in queries.

---

## 4. Dimension Tables

### dim_date
- `date_id` (PK, surrogate / `date`), `calendar_date`, `date_type` (weekday/weekend/holiday), `week_id`, `weekday_num`, `weekday_name`, `month`, `quarter`, `year`, `is_event_day`, `event_type_1..n`, `event_name_1..n`, `snap_w`/`snap_ca`/`snap_tx` flags, `is_observed` flag.

### dim_product
- `product_id` (PK, e.g., `HOBBIES_1_001`), `item_id`, `product_label`, `category_id`, `dept_id`, `category_name`, `dept_name`.

### dim_store
- `store_id` (PK), `store_name`, `state_id`, `state_name`, `region_id`, `region_name` (West/ Central / East).

### dim_category
- `category_id` (PK), `category_name` (e.g., Hobbies, Foods, Household).

### dim_department
- `dept_id` (PK), `dept_name`, `category_id` (FK).

### dim_event
- `event_id` (PK), `event_name`, `event_type`, `event_date`, `event_region_scope`.

*(Note: `dim_category` and `dim_department` could be collapsed into `dim_product` columns; they are kept as dimensions only if cross-product hierarchical analysis benefits from separate conformed dimensions. The final choice is documented in the ERD.)*

---

## 5. Fact / Core Tables

### fact_daily_sales  (Observed)
- `sales_id` (PK), `date_id` (FK→dim_date), `product_id` (FK), `store_id` (FK), `units_sold` (observed demand proxy), `demand_source` ('train'|'valid'|'eval'), `etl_run_id` (FK).

### fact_weekly_price  (Observed)
- `price_id` (PK), `week_id`, `product_id`, `store_id`, `sell_price`, `etl_run_id`.

### fact_product_store_demand  (Derived — aggregated demand statistics)
- `demand_stat_id` (PK), `product_id`, `store_id`, analysis window, `total_units`, `mean_daily_units`, `std_daily_units`, `cv` (volatility), `trend_slope`, `seasonal_index`, `demand_growth_rate`, `zero_demand_days`, `series_start`, `series_end`.

### fact_forecast  (Derived)
- `forecast_id` (PK), `model_id` (FK→model_registry), `product_id`, `store_id`, forecast origin date, `forecast_horizon`, `forecast_date`, `forecast_value`, `lower_bound`, `upper_bound`, `is_final`.

### fact_forecast_evaluation  (Derived)
- `eval_id` (PK), `model_id`, entity, validation window, `mae`, `rmse`, `wmae`, `wrmse`, `abs_error`, `pct_error`, `bias`.

### fact_inventory_simulation  (Simulated)
- `sim_id` (PK), `assumption_set_id`, `product_id`, `store_id`, date, `starting_inventory`, `demand_forecast`, `lead_time_demand`, `safety_stock`, `reorder_point`, `inventory_position`, `on_hand`, `orders_placed`, `reorder_qty`, `projected_stockout` (bool), `stockout_units`, `excess_inventory`, `days_of_inventory`, `service_level_achieved`.

### fact_replenishment_recommendation  (Simulated/Derived)
- `rec_id` (PK), `assumption_set_id`, `product_id`, `store_id`, decision date, `recommendation` (REORDER / MONITOR / REDUCE INVENTORY / HIGH STOCKOUT RISK / EXCESS INVENTORY / NO ACTION), `rationale`, `evidence_fields`, `impact_estimate`, `traceability_path`.

---

## 6. Metadata / Governance Tables

### etl_run_log
- `run_id` (PK), `pipeline`, `started_at`, `finished_at`, `status`, `records_processed`, `records_loaded`, `checksum_manifest`, `error_message`.

### data_quality_results
- `result_id` (PK), `run_id`, `check_name`, `table`, `column`, `severity`, `status` (pass/fail/warn), `metric_value`, `details`.

### model_registry
- `model_id` (PK), `model_name`, `model_family`, `params_json`, `training_window`, `validation_method`, `created_at`, `git_ref`, `is_selected` (bool).

---

## 7. Relationship Summary (ERD direction)

```
dim_category 1──n dim_department 1──n dim_product n──1 dim_store
                                                        │
dim_date 1────n fact_daily_sales ──n──1 dim_store ──────┘
         │            │                 │
         │            │                 ▼
         │            └────── n──1 dim_product n──1 dim_store
         └────────────n fact_weekly_price
fact_forecast ──n──1 model_registry
fact_forecast_evaluation ──n──1 model_registry
fact_inventory_simulation ──n──1 assumption set (config)
fact_replenishment_recommendation ──n──1 assumption set
```

## 8. Assumption Set (config)

A dedicated `assumption_set` configuration (parameter table or config file keyed by `assumption_set_id`) stores: `starting_inventory` rule, `lead_time` (days, mean/distribution), `service_level`, `safety_stock_formula` + parameters, `reorder_policy`, `reorder_quantity` rule, `demand_adjustment` (for scenarios). Every simulated table references it so results are reproducible and auditable.

## 9. ERD / Diagram Specification

A formal ERD diagram spec is maintained in `docs/erd.md` (see that file). The diagram is rendered in later phases; this document defines the entities, keys, and relationships.
