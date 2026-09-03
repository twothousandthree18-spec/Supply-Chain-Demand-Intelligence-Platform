# Data Dictionary — M5 Dataset

**Phase 1 — field-level dictionary for the acquired M5 files.**

This documents the fields of the M5 raw files and classifies each as
**OBSERVED** (supplied by M5) / **DERIVED** (computed later) / **SIMULATED**
(later inventory phases). Phase 1 only inventories OBSERVED fields.

---

## calendar.csv

| Column | Type | Description | Provenance |
|---|---|---|---|
| `wm_yr_wk` | int | Walmart week ID (year + week of year). | OBSERVED |
| `weekday` | str | Weekday name (Saturday…Friday). | OBSERVED |
| `wday` | int | Day of week index (1=Saturday … 7=Friday). | OBSERVED |
| `month` | int | Month of year. | OBSERVED |
| `year` | int | Calendar year. | OBSERVED |
| `d` | int | Day index (1…n) matching sales column suffix. | OBSERVED |
| `date` | date | Calendar date (YYYY-MM-DD). | OBSERVED |
| `event_name_1`, `event_name_2` | str | Named events occurring that day (NaN if none). | OBSERVED |
| `event_type_1`, `event_type_2` | str | Event type (e.g., Religious, Cultural, National, Sporting; NaN if none). | OBSERVED |
| `snap_CA`, `snap_TX`, `snap_WI` | int (0/1) | SNAP (food-stamp) promotion eligibility flag per state. | OBSERVED |

## sell_prices.csv

| Column | Type | Description | Provenance |
|---|---|---|---|
| `store_id` | str | Store code, e.g., `CA_1`. | OBSERVED |
| `item_id` | str | Product code, e.g., `HOBBIES_1_001`. | OBSERVED |
| `wm_yr_wk` | int | Walmart week ID. | OBSERVED |
| `sell_price` | float | Selling price (USD) for item/store/week. | OBSERVED |

## sales_train_validation.csv / sales_train_evaluation.csv

| Column | Type | Description | Provenance |
|---|---|---|---|
| `id` | str | Composite id = `item_id_store_id`, e.g., `HOBBIES_1_001_CA_1`. | OBSERVED |
| `item_id` | str | Product code. | OBSERVED |
| `dept_id` | str | Department code, e.g., `HOBBIES_1`. | OBSERVED |
| `cat_id` | str | Category code, e.g., `HOBBIES`. | OBSERVED |
| `store_id` | str | Store code. | OBSERVED |
| `state_id` | str | State code (`CA`, `TX`, `WI`). | OBSERVED |
| `d_1` … `d_1913` (validation) / `d_1941` (evaluation) | int | Daily units sold per day index. **OBSERVED demand proxy.** | OBSERVED |

**Note on provenance:** For this project the daily `d_*` values are treated as
the OBSERVED demand proxy. Any inventory quantities, stockouts, service levels,
or reorder logic computed in later phases are **SIMULATED / ASSUMPTION-based**
and never presented as observed data (see docs/dataset_strategy.md).

## sample_submission.csv (documentation only)

Defines the validation/evaluation submission format (sell prices + forecast
quantities per product/store/date). Used only to document the M5 forecast
horizon structure. Not loaded into the warehouse.

## Hierarchical identifiers (needed for Phase 2+ join keys)

- `item_id` → parsed into `category (cat_id)` + department (`dept_id`) → product.
- `store_id` → parsed into `state (state_id)` → store.
- Day `d` links to `calendar.csv` `d`; `date`, `event_*`, `snap_*`.
- `(item_id, store_id, wm_yr_wk)` links sales to `sell_prices.csv`.
