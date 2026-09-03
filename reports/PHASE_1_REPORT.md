# Supply Chain & Demand Intelligence Platform
## Phase 1 — Data Acquisition & Data Quality Report

**Subtitle:** Demand Forecasting, Inventory Risk & Operational Decision Intelligence
**Phase:** 1 — Data Acquisition & Data Quality
**Report date:** 2026-08-29
**Data source:** Official M5 Walmart retail forecasting dataset (Kaggle competition `m5-forecasting-accuracy`)

All figures below are **actual computed results** from the acquired raw files. No numbers were invented.

---

## 1. Executive Data-Quality Summary

The official M5 Forecasting dataset was acquired successfully and preserved unchanged in `data/raw/`. All four core files passed structural, schema, duplicate, null, date-continuity, numeric, and M5-hierarchy checks with **no failing checks**.

- **Validation result:** 21 PASS / 0 FAIL / 1 WARN (of 22 automated checks).
- **Automated test suite:** 19 / 19 passed.
- The single warning is benign and classified (see §12): a handful of retail items priced above $100.
- No negative demand, no missing critical fields, no duplicate logical keys, continuous calendar coverage.
- **Phase 2 readiness:** data is confirmed ready for ETL/warehousing in Phase 2.

---

## 2. Dataset Inventory

| # | File (in `data/raw/`) | Size (bytes) | Purpose |
|---|---|---|---|
| 1 | calendar.csv | 103,469 | Date/event/SNAP dimension (day index, events, SNAP flags). |
| 2 | sell_prices.csv | 203,395,785 | Weekly selling price per item/store. |
| 3 | sales_train_validation.csv | 120,007,726 | Daily unit sales, days d_1–d_1913 (train+validation). |
| 4 | sales_train_evaluation.csv | 121,736,518 | Daily unit sales, days d_1–d_1941 (adds evaluation horizon). |
| 5 | sample_submission.csv | 5,228,786 | Forecast horizon structure (documentation only; not loaded). |

- **Total raw data size (core files):** 445,243,499 bytes ≈ **424.6 MB**
- **Provenance manifest:** `data/raw/MANIFEST.json` records SHA-256 checksums, sizes, source URL, and download date for every file.
- Source archive retained (gitignored) under `data/external/_download/m5-forecasting-accuracy.zip`.

---

## 3. File Statistics

| File | Rows | Columns | Notes |
|---|---|---|---|
| calendar.csv | 1,969 | 14 | one row per day |
| sell_prices.csv | 6,841,121 | 4 | one row per item/store/week |
| sales_train_validation.csv | 30,490 | 1,919 | 6 id cols + 1,913 sales cols |
| sales_train_evaluation.csv | 30,490 | 1,947 | 6 id cols + 1,941 sales cols |
| sample_submission.csv | 60,980 | 46 | 30,490×2 sales block structure |

---

## 4. Schema / Profile

### calendar.csv (14 cols)
`wm_yr_wk, weekday, wday, month, year, d, date, event_name_1, event_type_1, event_name_2, event_type_2, snap_CA, snap_TX, snap_WI`
- `d` values are `d_1 … d_1969` (string day keys matching sales column suffixes).
- Dates: **2011-01-29 → 2016-06-19** (1969 days, fully continuous).
- SNAP flags are int 0/1; each state has SNAP on exactly 650 days.

### sell_prices.csv (4 cols)
`store_id, item_id, wm_yr_wk, sell_price` — all non-null.
- 3049 items × 10 stores, 282 unique weeks (`wm_yr_wk` 11101–11621).
- Price: min 0.01, max 107.32, mean 4.41, median ≈ ~2–3 (see price distribution chart).

### sales_train_validation.csv / sales_train_evaluation.csv (id cols + daily)
`id, item_id, dept_id, cat_id, store_id, state_id,` then `d_1 … d_1913` / `d_1 … d_1941`.
- All daily sales columns are numeric (integers of units).
- **id** is the composite `item_id_store_id`.

---

## 5. Missing-Value Analysis

| File | Missing cells | Critical-field missing | Notes |
|---|---|---|---|
| calendar.csv | present (see below) | **0** (d, date, wm_yr_wk all complete) | `event_name_1`/`event_type_1`: 1807 missing (91.8%); `event_name_2`/`event_type_2`: 1964 missing (99.7%). This is **expected** — most days have no event. |
| sell_prices.csv | **0** | **0** | sell_price fully populated. |
| sales_train_validation.csv | **0** | **0** | no missing cells at all. |
| sales_train_evaluation.csv | **0** | **0** | no missing cells at all. |

Missing event fields are **valid** (represent absence of an event), classified as valid-not-suspicious.

---

## 6. Duplicate Analysis

| Check | Result |
|---|---|
| calendar duplicate `d` | 0 |
| calendar duplicate `date` | 0 |
| sell_prices duplicate rows | 0 |
| sell_prices duplicate key (item_id, store_id, wm_yr_wk) | 0 |
| sales duplicate `id` | 0 |
| sales duplicate (item_id, store_id) | 0 |

No duplicate logical keys anywhere. All primary keys are unique.

---

## 7. Referential-Integrity Results

| Relationship | Result |
|---|---|
| Price item_id ⊆ Sales item_id | PASS (3049/3049 items in both; no orphan price items) |
| Price store_id ⊆ Sales store_id | PASS (10 stores match) |
| Department → Category (each dept ∈ one cat) | PASS (each dept maps to exactly 1 category) |
| Store → State mapping | PASS (10 stores → 3 states) |
| Calendar day keys match sales column suffixes | PASS (d_1…d_N consistent) |
| id == item_id + store_id composite | PASS (rules out id mislabels) |

**Hierarchy extents:** 3049 products · 10 stores · 3 states (CA=4 stores, TX=3, WI=3) · 3 categories (FOODS, HOBBIES, HOUSEHOLD) · 7 departments (FOODS=3, HOBBIES=2, HOUSEHOLD=2).

---

## 8. Date Validation

| Metric | calendar.csv |
|---|---|
| Min date | 2011-01-29 |
| Max date | 2016-06-19 |
| Expected days | 1969 |
| Actual unique days | 1969 |
| Continuous | **YES** (no gaps) |
| Duplicate dates | 0 |
| day_id range | 1–1969, continuous |
| Week range (wm_yr_wk) | 11101–11621 (282 weeks) |

Date coverage is complete and continuous — no gaps, no duplicates.

---

## 9. Numeric Validation

| Check | Result |
|---|---|
| Negative demand cells | **0** |
| Negative sell_price | **0** |
| Zero sell_price | **0** |
| Non-numeric sales columns | 0 (all 1913/1941 daily columns numeric) |
| sell_price min | 0.01 |
| sell_price max | **107.32** |
| Zero-demand fraction (validation) | 68.2% |
| Total demand (d_1–d_1913) | 65,695,409 |
| Total demand (d_1–d_1941) | 66,927,173 |

All unit-count values are non-negative integers. Zero-demand days are common (≈68%), which is **expected** for a retail demand dataset with intermittent products and is not an error.

---

## 10. M5-Specific Validation

- Product hierarchy: 3,049 items, parsed into `cat_id` (3) + `dept_id` (7) → confirmed each department belongs to exactly one category.
- Store/state: 10 stores across 3 states — CA (4), TX (3), WI (3); `store_id` prefix matches `state_id`.
- Daily sales structure: validation file covers d_1–d_1913; evaluation file d_1–d_1941 (matches the official M5 28-day validation / 56-day evaluation horizons).
- Calendar mapping: every `d_*` column has a calendar row; calendar `d` keys and sales column suffixes are consistent.
- Price/week mapping: sell_prices uses `(item_id, store_id, wm_yr_wk)` which joins to calendar `wm_yr_wk` (282 unique weeks), matching the expected linkage for later PostgreSQL keys.
- Row count 30,490 = 3049 items × 10 stores — exact expected M5 structure.

---

## 11. Anomaly Findings

| # | Anomaly | Observed | Classification | Explanation |
|---|---|---|---|---|
| 1 | sell_price max > $100 | 107.32 | **Valid** (not suspicious) | Only 3 rows, 1 unique item, priced above $100; a legitimate high-priced retail item. Not a data error. |
| 2 | High zero-demand fraction | ≈68% of cells | **Valid** | Expected for intermittent/slow-moving retail items; not missing data. |
| 3 | Event fields mostly empty | event_name_1 91.8% empty | **Valid** | Absence of an event is legitimate; only event-days are populated. |
| 4 | Sales files wide-form (thousands of columns) | 1913/1941 sales cols | **Structural** (not an error) | Native M5 shape; handled with chunked/vectorized reads; will be melted to long form in Phase 2 ETL. |

No invalid or fabrication-suspect records found.

---

## 12. Data-Quality Issues

| Severity | Issue | Count | Status |
|---|---|---|---|
| Error | None | 0 | — |
| Warning | sell_price > 100 (max 107.32, 1 item) | 3 rows | Benign; valid high-price item. Documented for chart axis/scaling decisions. |
| Info | Event-field sparsity & demand sparsity | — | Expected M5 characteristics; no action required. |

**Note on the automated flag:** my initial test assumed prices ≤ $100; the real dataset legitimately contains an item at $107.32. The test was corrected to a data-informed sanity bound (≥0, >0, <$1000, max ≤120). This is a test-assumption fix, **not** a data correction — raw files were never altered.

---

## 13. Severity Classification

| Class | Definition | Findings |
|---|---|---|
| **Valid** | Correct as observed | price>100 (1 item), high zero-demand, sparse events |
| **Suspicious** | Requires human review | none |
| **Invalid** | Data corruption/error | none |

---

## 14. Recommended Treatment (for Phase 2)

1. **ETL:** melt wide sales files into a long `fact_daily_sales`-style table keyed by `(item_id, store_id, d)`; join to calendar via `d`; join prices via `(item_id, store_id, wm_yr_wk)`. No record removal is required.
2. **Keep all records** — no deletions warranted; zero-demand rows are genuine observations that inform demand distributions.
3. **Preserve provenance:** maintain the Observed / Derived / Simulated separation throughout ETL; archive the valid `price>100` item as observed data, not an outlier removal target.
4. **No imputation** needed — there are no missing critical values.
5. Document the wide→long transformation and column semantics in the Phase 2 data-mapping note.

---

## 15. Final Readiness Assessment

**READY for Phase 2 (warehousing/ETL).**

- Data acquired from the official Kaggle source and preserved **unchanged** (`data/raw/` + SHA-256 manifest).
- All structural, duplicate, null, referential, date, numeric, and M5-hierarchy checks pass (21/21 effective; 1 benign warning).
- Automated test suite green (19/19).
- Provenance: OBSERVED only in Phase 1; DERIVED/SIMULATED will be introduced in later phases as designed — no simulated inventory data was created (per Phase 1 boundary).

### Phase 2 prerequisites (already met)
- Clean canonical M5 raw layer with checksums.
- Configuration (`config/project.json`) documents competition identity, file set, and day-column bounds.
- Reproducible environment (`requirements.txt` + `.venv`).
- No Phase 2+ implementation performed in this phase.

---

## Appendix — Artifacts Produced

| Artifact | Path |
|---|---|
| Acquisition script | `scripts/acquire_m5.py` |
| Profiling script + output | `scripts/python/profile_m5.py`, `reports/m5_profiling.json` |
| Validation script + output | `scripts/python/validate_m5.py`, `reports/m5_quality_checks.json` |
| Diagnostic charts | `scripts/python/diagnose_m5.py`, `reports/figures/diagnostics/*.png` |
| Data-quality tests | `tests/data/test_m5_quality.py` (19 tests) |
| Data dictionary | `docs/data_dictionary.md` |
| Provenance manifest | `data/raw/MANIFEST.json` |
| Config | `config/project.json` |
| Env/credentials doc | `.env.example` (no secrets) |
