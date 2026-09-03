# Warehouse Architecture — Phase 2 Implementation

**Phase:** 2 — Data Engineering & PostgreSQL Analytical Warehouse (implemented)
**Status:** Built, loaded, reconciled, and verified. Database ~16 GB on `supply_chain_intelligence`.

This document describes the **implemented** warehouse as of Phase 2 completion. The original Phase 0 design
lives in `docs/database_architecture.md`; any intentional deviations introduced during implementation are
called out under [8. Design decisions](#8-design-decisions).

All row counts in this document are **actual computed results** from the deployed database — nothing is inferred.

---

## 1. Overview & Purpose

PostgreSQL is the analytical single source of truth for the platform. Phase 2 implemented the warehouse schema
(star/snowflake hybrid), a resumable/idempotent ETL that loads the raw M5 files (from Phase 1 acquisition) into
staging and then into conformed dimensions and fact tables, enforced referential integrity, built indexes, and
reconciled every table against the Phase 1 baselines (`reports/m5_profiling.json`).

Deliverables:

- **Schema DDL** in `sql/schema/`, `sql/staging/`, `sql/dimensions/`, `sql/facts/`, `sql/indexes/`,
  `sql/validation/`, `sql/utilities/`.
- **ETL engine** `src/etl/build_warehouse.py` + `src/etl/db_utils.py`.
- **Detached launcher** `scripts/run_etl_detached.ps1`.
- **Read-only acceptance tests** `tests/sql/test_warehouse.py` (19 tests, all pass).
- **Final report** `reports/PHASE_2_REPORT.md`.

---

## 2. Source Data (Phase 1 inputs)

Acquired and validated in Phase 1; preserved unchanged under `data/raw/`.

| File | Used for | Key facts |
|---|---|---|
| `calendar.csv` | `dim_date`, `stg_calendar` | 1,969 calendar days (2011-01-29 → 2016-06-19), 282 weeks |
| `sell_prices.csv` | `fact_weekly_price`, `stg_sell_prices` | 6,841,121 weekly (item,store) prices |
| `sales_train_evaluation.csv` | `fact_daily_sales`, `stg_sales_*` | Full **observed** daily demand d_1..d_1941 |

**ETL source decision:** daily demand is loaded from `sales_train_evaluation.csv` only. This file is a strict
superset of `sales_train_validation.csv` for the observed horizon (d_1..d_1941), so loading only it avoids
duplicate rows while capturing the full observed demand. Total observed demand = **66,927,173**, which matches
the Phase 1 evaluation baseline exactly.

**Fact days = 1941** (observed range d_1..d_1941), not the full 1,969 calendar days — correct for observed-only
data. `dim_date` still holds the complete 1,969-day calendar for later derived/simulated stages.

---

## 3. Architecture

```
 data/raw (CSV)                            PostgreSQL: supply_chain_intelligence
  calendar.csv ──┐
  sell_prices.csv┼─► stg_calendar        ┌───────────── Staging ─────────────┐
                 │    stg_sell_prices    │ stg_calendar, stg_sell_prices,   │
  sales_train_   │    stg_sales_meta     │ stg_sales_meta, stg_sales_daily  │
  evaluation.csv┘    stg_sales_daily ────┴───────────────────────────────────┘
                           │  dims (20_dims.sql)
                           ▼
              ┌───── Dimensions ─────┐
              │ dim_product (3,049)  │  dim_store (10)
              │ dim_date  (1,969)    │  dim_category (3)
              │ dim_department (7)   │
              └──────────────────────┘
                           │  facts (30_load_facts.sql)
                           ▼
              ┌───── Facts ──────────┐
              │ fact_daily_sales     │  59,181,090 rows (observed)
              │ fact_weekly_price    │   6,841,121 rows (observed)
              └──────────────────────┘
                           │  indexes (40_indexes.sql)
                           ▼
              ┌───── Metadata ───────┐
              │ etl_run_log          │  audit: run_id=3 SUCCESS
              │ data_quality_results │
              └──────────────────────┘
```

Staging → warehouse follows a classic ELT shape: raw CSVs are copied into staging, the staging layer is
transformed into conformed dimensions, then facts are loaded in a single transaction with surrogate-key joins.

---

## 4. Table / Data Model

### 4.1 Dimension tables (all with enforced UNIQUE natural keys)

| Table | Row count | Natural key (UNIQUE) |
|---|---|---|
| `dim_product` | 3,049 | `product_id` (e.g. `HOBBIES_1_001`) |
| `dim_store` | 10 | `store_id` (CA_1..CA_4, TX_1..TX_3, WI_1..WI_3) |
| `dim_date` | 1,969 | `date_id` (surrogate `date`) |
| `dim_category` | 3 | `category_id` (Foods, Hobbies, Household) |
| `dim_department` | 7 | `dept_id` |

### 4.2 Fact tables (composite keys UNIQUE-enforced)

**`fact_daily_sales`** — one row per (product, store, day) of **observed** demand.

- Columns: `sales_id` (PK bigint), `product_surr_id`, `store_surr_id`, `date_id`, `units_sold` (int),
  `demand_source` (= `'observed'`), `data_provenance` (= `'observed'`), `etl_run_id`.
- Composite key **UNIQUE (product_surr_id, store_surr_id, date_id)**.
- 59,181,090 rows = 3,049 products × 10 stores × 1,941 observed days (full Cartesian coverage, no gaps).
- Sum of `units_sold` = **66,927,173** (matches Phase 1 baseline).
- FKs → `dim_product`, `dim_store`, `dim_date`.

**`fact_weekly_price`** — one row per (product, store, week) where the item was sold.

- Columns: `price_id` (PK bigint), `product_surr_id`, `store_surr_id`, `wm_yr_wk`, `week_id`,
  `sell_price` (numeric), `data_provenance` (= `'observed'`), `etl_run_id`.
- Composite key **UNIQUE (product_surr_id, store_surr_id, wm_yr_wk)**.
- 6,841,121 rows (matches source `sell_prices.csv` exactly).
- `sell_price` range **[0.01, 107.32]** (107.32 is the benign Phase 1 price WARN — items > $100).
- Price rows exist **only** for (product, store, week) combos where the item was sold, so the table is not the
  full Cartesian product of all products × stores × weeks — this is correct, not a gap.

### 4.3 Stage tables

| Table | Row count | Notes |
|---|---|---|
| `stg_calendar` | 1,969 | calendar.csv |
| `stg_sell_prices` | 6,841,121 | sell_prices.csv |
| `stg_sales_meta` | 30,490 | item metadata (3,049 items × 10 stores) |
| `stg_sales_daily` | 59,181,090 | melted long-form daily sales from evaluation file |

### 4.4 Metadata tables

- `etl_run_log` — records every ETL run; run_id=3 = SUCCESS; stale `running` runs 1 & 2 were marked failed at
  startup (idempotent/resumable guard).
- `data_quality_results` — repository for quality/validation records.

---

## 5. Lineage

```
sales_train_evaluation.csv (d_1..d_1941, wide per-id)
        │  melt (single transaction)            ── 700.8 s
        ▼
stg_sales_daily (59,181,090 long-form)  ──►  dim_product / dim_store
        │  join surrogate keys
        ▼
fact_daily_sales (59,181,090)          demand_source='observed', data_provenance='observed'

sell_prices.csv ──► stg_sell_prices ──► dim_product / dim_store / dim_date(week_id)
                                            │
                                            ▼
                            fact_weekly_price (6,841,121)
```

The provenance markers (`demand_source`, `data_provenance`) carry the lineage through the fact tables so that
observed vs. derived vs. simulated data remains separable (per the Phase 0 tripartition design).

---

## 6. Validation / Reconciliation

Reconciliation is performed by the ETL at the end of a run and cross-checks every table against Phase 1 baselines:

| Check | Result |
|---|---|
| dim_product | 3,049 ✓ |
| dim_store | 10 ✓ |
| dim_date | 1,969 ✓ |
| dim_category | 3 ✓ |
| dim_department | 7 ✓ |
| fact_daily_sales rows | 59,181,090 ✓ |
| total observed demand | 66,927,173 ✓ |
| fact_weekly_price rows | 6,841,121 ✓ |
| price range | [0.01, 107.32] ✓ |
| orphans (fact → dim) | 0 ✓ |
| duplicate sales keys | 0 ✓ |
| duplicate price keys | 0 ✓ |

The automated acceptance suite `tests/sql/test_warehouse.py` (19 tests, **all read-only / SELECT only**)
independently re-verifies: required tables exist, provenance columns present, dimension counts,
product↔department↔category and store↔state hierarchies, fact row counts, natural-key uniqueness,
composite-key uniqueness (via the DB-enforced UNIQUE constraints), PK uniqueness, FK constraints, no-orphan
guarantees (via FKs), demand total, non-negative units, price range, reconciliation vs. Phase 1, and ETL run
success.

**Runtime:** the suite completes in ~27 s by verifying DB-enforced constraints (UNIQUE/PK/FK from the catalog)
instead of replaying 59M-row GROUP BY / anti-join scans for guarantees the database already physically enforces.

---

## 7. Indexes & ETL execution / performance

Indexes are applied in `sql/indexes/40_indexes.sql`:

- Primary keys on all dimension and fact surrogate IDs.
- Unique composite keys on `fact_daily_sales (product_surr_id, store_surr_id, date_id)` and
  `fact_weekly_price (product_surr_id, store_surr_id, wm_yr_wk)`.
- Unique natural keys on all dimensions.
- Foreign-key columns are indexed to support joins/RI.

**ETL execution (run_id=3, detached):**

| Stage | Time |
|---|---|
| Melt sales → staging (single transaction) | 700.8 s |
| Dimensions | 1.0 s |
| Facts (single transaction) | 5,467.3 s |
| Indexes | 370.9 s |
| **Total** | **~2 h** (10:03 → 12:05) |

**Design notes relevant to runtime:**

- The sales melt commits **all 59,181,090 staging rows in one transaction** (all-or-nothing); `stg_sales_daily`
  stays at 0 until commit. This is by design.
- `30_load_facts.sql` inserts **both** fact tables in one transaction, committing only at file end — fact counts
  show 0 until the whole file completes. This caused apparent "hang" confusion during progress monitoring but is
  intended all-or-nothing behaviour.
- The ETL is **resumable/idempotent**: existing populated stage tables are reused (`[reuse]`), stale `running`
  runs are marked failed on startup, and a repeat run converges rather than duplicating data.
- Database size after load: **~16 GB**.

**Launcher bug fixed relative to Phase 2 development:** the project path contains spaces
(`D:\M Projects\...`); `Start-Process -ArgumentList` with an array did not quote elements with spaces, so Python
received only `D:\M`. `scripts/run_etl_detached.ps1` now builds a single pre-quoted argument string.

---

## 8. Design decisions

1. **Load only `sales_train_evaluation.csv` for demand.** Strict superset of the validation file over the observed
   horizon; avoids duplicate rows and matches the Phase 1 baseline.
2. **Fact days = 1,941** (observed d_1..d_1941); `dim_date` keeps the full 1,969-day calendar for later stages.
3. **Price rows only where sold.** `fact_weekly_price` is not the full product×store×week Cartesian product;
   prices exist only for sold combos (matches `sell_prices.csv`).
4. **Surrogate-key star/snowflake** with conformed dimensions and a separate `fact_weekly_price` (weekly grain),
   consistent with the Phase 0 model. There is **no hourly fact** in the model (N/A — the 7 facts are daily sales,
   weekly price, product-store demand, forecast, forecast evaluation, inventory simulation, replenishment).
5. **DB-enforced integrity over runtime re-scans.** Uniqueness/orphan guarantees live in UNIQUE/PK/FK
   constraints; the acceptance suite verifies the constraints (fast, authoritative) instead of scanning 59M rows
   on every test run.
6. **Read-only tests.** `tests/sql/` never issues DDL/DML/ETL (SELECT only).
