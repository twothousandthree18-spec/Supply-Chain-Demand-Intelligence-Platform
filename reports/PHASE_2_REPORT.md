# Supply Chain & Demand Intelligence Platform
## Phase 2 — Data Engineering & PostgreSQL Analytical Warehouse Report

**Subtitle:** Demand Forecasting, Inventory Risk & Operational Decision Intelligence
**Phase:** 2 — Data Engineering & Analytical Warehouse
**Report date:** 2026-08-30
**Database:** `supply_chain_intelligence` (PostgreSQL 127.0.0.1:5432), ~16 GB
**Data source:** Official M5 Walmart retail forecasting dataset (Phase 1 acquisition)

All figures below are **actual computed results** from the deployed database and the ETL run log
(`reports/etl/etl_build.log`). No numbers were invented.

---

## 1. Executive Summary

Phase 2 built the analytical warehouse on PostgreSQL: a star/snowflake schema, a resumable/idempotent ETL from
the Phase 1 raw files, enforced referential integrity, indexes, and an auditable metadata layer. The ETL run
**succeeded** (run_id=3), and every table was reconciled exactly against the Phase 1 baselines — no orphans, no
duplicate keys, no gaps.

- **ETL result:** run_id=3 **SUCCESS** (runs 1 & 2 stale `running` were marked failed at startup).
- **Warehouse tables:** 5 dimensions, 2 observed facts, 4 staging tables, 2 metadata tables.
- **Facts:** `fact_daily_sales` = **59,181,090** rows (observed demand); `fact_weekly_price` = **6,841,121** rows.
- **Total observed demand:** **66,927,173** — matches Phase 1 exactly.
- **Referential integrity:** 0 orphans, 0 duplicate sales keys, 0 duplicate price keys.
- **Automated acceptance suite:** **19 / 19 passed** (read-only, ~27 s).
- **Database size after load:** ~16 GB.

---

## 2. Acceptance Criteria & Results

| # | Criterion | Result | Evidence |
|---|---|---|---|
| A1 | Schema DDL versioned & reproducible under `sql/` | **PASS** | `sql/schema|staging|dimensions|facts|indexes|validation|utilities/` |
| A2 | Dimensions conformed & unique natural keys | **PASS** | dims: 3,049 / 10 / 1,969 / 3 / 7; tested |
| A3 | Facts loaded: `fact_daily_sales` | **PASS** | 59,181,090 rows; tested |
| A4 | Facts loaded: `fact_weekly_price` | **PASS** | 6,841,121 rows; tested |
| A5 | Observed demand total matches Phase 1 | **PASS** | 66,927,173 = 66,927,173 |
| A6 | Referential integrity (no orphans, FKs) | **PASS** | orphans=0; FKs tested |
| A7 | No duplicate keys (PK & composite) | **PASS** | UNIQUE/PK constraints; dup=0 |
| A8 | ETL is resumable/idempotent | **PASS** | run_id=3 reused stage rows; stale runs marked failed |
| A9 | ETL audited via `etl_run_log` | **PASS** | run_id=3 SUCCESS recorded |
| A10 | Automated acceptance tests pass | **PASS** | `tests/sql`: 19 / 19 |
| A11 | Documentation produced | **PASS** | `docs/warehouse_architecture.md`; this report |
| A12 | Final verification completed | **PASS** | see §5 |

---

## 3. Warehouse Inventory

### 3.1 Dimensions

| Table | Row count | Natural key |
|---|---|---|
| `dim_product` | 3,049 | `product_id` |
| `dim_store` | 10 | `store_id` (CA=4, TX=3, WI=3) |
| `dim_date` | 1,969 | `date_id` |
| `dim_category` | 3 | Foods, Hobbies, Household |
| `dim_department` | 7 | 3 FOODS, 2 HOBBIES, 2 HOUSEHOLD |

### 3.2 Facts

| Table | Rows | Composite UNIQUE key | Grain |
|---|---|---|---|
| `fact_daily_sales` | 59,181,090 | (product_surr_id, store_surr_id, date_id) | product × store × observed day |
| `fact_weekly_price` | 6,841,121 | (product_surr_id, store_surr_id, wm_yr_wk) | product × store × week (where sold) |

Both facts carry `demand_source` / `data_provenance` = `'observed'` and `etl_run_id`.

### 3.3 Staging

| Table | Rows |
|---|---|
| `stg_calendar` | 1,969 |
| `stg_sell_prices` | 6,841,121 |
| `stg_sales_meta` | 30,490 |
| `stg_sales_daily` | 59,181,090 |

### 3.4 Metadata

- `etl_run_log` (run_id=3 SUCCESS), `data_quality_results`.

---

## 4. ETL Execution & Performance (run_id=3)

| Stage | Time |
|---|---|
| Melt sales → staging (single transaction) | 700.8 s |
| Dimensions | 1.0 s |
| Facts (single transaction) | 5,467.3 s |
| Indexes | 370.9 s |
| **Total** | **~2 h** (10:03 → 12:05) |

Reconciliation (from ETL log):

```
dim_product=3049  dim_store=10  dim_date=1969  dim_category=3  dim_department=7
fact days=1941  fact_rows=59,181,090  total demand=66,927,173
price rows=6,841,121  price [0.01,107.32]
orphans=0  dup_sales_keys=0  dup_price_keys=0
```

---

## 5. Test Results

| Suite | Result |
|---|---|
| `tests/sql/test_warehouse.py` (19 tests, read-only) | **19 / 19 PASS** (~27 s) |

19 tests: required tables, provenance columns, dimension counts, product–department–category hierarchy,
store–state hierarchy, fact daily sales count, fact weekly price count, dimension natural-key uniqueness,
fact composite-key uniqueness, fact PK uniqueness, FK constraints defined, no-orphan sales, no-orphan prices,
product–department chain, total observed demand, units non-negative, price range, reconciliation vs Phase 1,
ETL run success.

**Note on test design:** uniqueness / no-orphan guarantees are criss-checked against the DB-enforced
UNIQUE / PK / FK constraints (fast, authoritative) rather than replaying 59M-row GROUP BY / anti-join scans,
because the database physically enforces these invariants.

---

## 6. Final Verification

The full phase-2 acceptance was verified end-to-end:

1. **Schema present & populated** — verified against the live database (dims, facts, staging, metadata).
2. **ETL success** — `etl_build.log` shows `=== DONE (run_id=3 SUCCESS) ===` with all reconciliations passing.
3. **Automated tests** — 19 / 19 pass on the live DB (read-only).
4. **Reconciliation** — every count/demand figure equals its Phase 1 baseline; 0 orphans, 0 duplicate keys.

### Warnings / non-blocking observations

- **W1 (benign):** highest `sell_price` = 107.32 (> $100) — carried over from the Phase 1 price WARN; real M5
  data, not a defect.
- **W2 (informational):** the sales melt and fact loads are single-transaction all-or-nothing by design, so
  interim row counts during an ETL run show 0 until commit; this is intended and can look like a "hang."
- **W3 (informational):** there is **no** `fact_hourly_sales` table — the Phase 0 model defines 7 facts (daily
  sales, weekly price, product-store demand, forecast, forecast evaluation, inventory simulation, replenishment);
  an hourly table is N/A.

---

## 7. Phase 2 → Phase 3 Readiness

The warehouse is complete and verified. With dimensions, facts, integrity, indexes, and metadata in place, the
platform is ready for Phase 3 (SQL analytical layer / KPI definitions, forecasting, inventory simulation) on a
trusted, reconciled foundation.
