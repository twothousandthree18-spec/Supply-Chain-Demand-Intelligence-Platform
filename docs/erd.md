# Entity-Relationship Diagram (ERD) Specification

**Phase 0 — Design only. No schema created.**

## 1. Notation

```
PK  = Primary Key
FK  = Foreign Key
1..n = one-to-many (1 on the left, n on the right)
```

## 2. Textual ERD

```
dim_category  ──1..n── dim_department ──1..n── dim_product
                                                   │
                                                   ▼
                                              n──1 dim_store
  
dim_date ──1..n── fact_daily_sales  ──n──1 dim_product
   │               │      │
   │               │      └──n──1 dim_store
   │               │
   │               └──(etl_run_id → etl_run_log)
   │
   └──1..n── fact_weekly_price ──n──1 dim_product
                     │
                     └──n──1 dim_store

dim_event ──n──1 dim_date   (calendar/event linkage)

model_registry ──1..n── fact_forecast ──n──1 dim_product
                     │                      └──n──1 dim_store
                     │
                     └──1..n── fact_forecast_evaluation

assumption_set ──1..n── fact_inventory_simulation ──n──1 dim_product
                                      │                    └──n──1 dim_store
assumption_set ──1..n── fact_replenishment_recommendation
```

## 3. Key Relationships (1..n)

1. **dim_category → dim_department**: a category contains many departments.
2. **dim_department → dim_product**: a department contains many products.
3. **dim_product → fact_daily_sales**: 1 product has many daily sales records.
4. **dim_store → fact_daily_sales**: 1 store has many sales records.
5. **dim_date → fact_daily_sales / fact_weekly_price**: 1 date/week drives many facts.
6. **dim_event → dim_date**: events attach to dates (calendar).
7. **model_registry → fact_forecast / fact_forecast_evaluation**: 1 registered model backs many forecast rows.
8. **assumption_set → fact_inventory_simulation / fact_replenishment_recommendation**: 1 assumption set governs many simulated rows.

## 4. Fact-Grain Notes

- **fact_daily_sales:** grain = (product_id, store_id, date_id) — one row per product/store/day.
- **fact_weekly_price:** grain = (product_id, store_id, week_id).
- **fact_product_store_demand:** grain = (product_id, store_id) per analysis window.
- **fact_forecast:** grain = (model_id, product_id, store_id, forecast_date).
- **fact_inventory_simulation:** grain = (assumption_set_id, product_id, store_id, date).
- **fact_replenishment_recommendation:** grain = (assumption_set_id, product_id, store_id, decision date).

## 5. Optimization Note

`dim_category` and `dim_department` are retained as separate conformed dimensions only if cross-entity hierarchy joins benefit; otherwise they may be collapsed into `dim_product` columns (e.g., `category_name`, `dept_name`). This is an implementation-time decision reflected in `database_architecture.md` and resolved when DDL is written in Phase 1. The canonical ERD diagram image will be generated here in a later phase from this specification.
