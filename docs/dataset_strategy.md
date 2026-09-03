# Dataset Strategy — M5 Walmart Retail Forecasting Dataset

**Phase 0 — Documentation only. The dataset has NOT been downloaded.**

---

## 1. Chosen Dataset

- **Primary dataset:** M5 "Accuracy" and "Uncertainty" — Walmart retail sales forecasting competition data (Kaggle, 2020).
- **Acquisition (future phase):** Official Kaggle download. Downloading is explicitly **out of scope** for Phase 0.

## 2. Why This Dataset

The M5 dataset is chosen because it directly serves the primary business question ("Can a company use historical demand data to forecast future demand, identify inventory risks, and make better replenishment decisions?"):

- **Product hierarchy:** 3,049 products organized into departments and categories, enabling product-level and category-level contribution analysis.
- **Stores:** 10 Walmart stores, enabling store-level and cross-store comparison.
- **States/regions:** Stores map to 3 states (CA, TX, WI) in 3 regions (West, Central, East), enabling regional analysis.
- **Daily historical sales:** ~1.9M daily unit-sales observations across ~1,941 days, giving genuine daily granularity for demand/sales analytics.
- **Calendar & events:** An events calendar with major religious, cultural, national and sporting events, enabling event/promotion-related demand analysis.
- **Selling prices:** Weekly selling price series per item/store, enabling price–demand relationships.

Combined, these features support **sales/commercial analysis, demand modelling, time-series forecasting, inventory simulation, scenario analysis, and decision support** — the full analytical scope of the platform — from a single, well-documented, publicly available source.

## 3. Included Files (planned)

- `calendar.csv` — date-level calendar with weekday, event names/type, SNAP activity.
- `sell_prices.csv` — weekly selling price per product/store.
- `sales_train_validation.csv` / `sales_train_evaluation.csv` — daily unit sales with product/store identifiers.
- `sample_submission.csv` — submission structure describing the forecast horizon (used to understand the day-partition split).

## 4. IMPORTANT LIMITATION

> The public M5 data does **NOT** provide actual inventory levels, purchase orders, supplier lead times, or actual stockout records.

This is the single most important analytical honesty constraint on the whole project. Because true inventory data is absent, the platform cannot claim to measure *real* inventory or *real* stockouts.

## 5. Mandatory Data Tripartition

To preserve analytical honesty, all later phases MUST explicitly separate three categories:

### A. OBSERVED DATA (actual source fields)
- Daily unit sales (observed demand proxy).
- Weekly selling price.
- Calendar / event / SNAP flags.
- Product, store, state, region, department, category hierarchy.

### B. DERIVED DATA (calculated from observed data)
- Revenue, growth, contribution.
- Demand statistics: trend, seasonality, volatility, demand growth.
- Forecasts and forecast-accuracy metrics.
- Demand distribution statistics used to size stock.

### C. SIMULATED DATA / ASSUMPTIONS (operational settings we choose)
- Starting inventory (we must assume a value).
- Supplier lead time (assumed, constant or distributional).
- Service level / target fill rate (assumed policy).
- Safety stock policy (formula + parameters).
- Reorder point and reorder quantity policy (e.g., reorder point / economic order logic).
- Simulated stockouts (derived from the above assumptions).

### Labelling rule (mandatory in every artifact)
- Simulated inventory, simulated stockouts, and all assumed inputs MUST be labeled **"Simulated / Assumption"**.
- **Never** present simulated values as real company data.
- Any dashboard, report, or web page that shows inventory/stockout figures must display the assumption set and classify each metric as Observed / Derived / Simulated.

## 6. Phase 1 Acquisition Status

**Status:** Acquisition infrastructure READY; dataset download **BLOCKED on API-key download permission**.

- Source: official Kaggle competition **`m5-forecasting-accuracy`** (authentication-gated).
- Authentication is **verified working**: `kaggle competitions list` succeeds (token valid).
- **Blocked on:** the Kaggle API token is **denied the `datasets.get` permission**. Every data download — both a test public dataset and the M5 competition files — returns:
  - `403 - Forbidden - Permission 'datasets.get' was denied` (CLI 1.6.17), or
  - `403 Client Error: Forbidden` (CLI 2.2.4).
- This is a **token/account permission issue, not a CLI compatibility issue** — reproduced on both CLI versions. No authoritative, credential-free distribution of the raw M5 files exists.

### Resolve the download-permission denial (user/account action required)

The Kaggle account/API token does not currently hold `datasets.get` permission. Required steps on Kaggle:
1. Log in to the Kaggle account that owns the API token.
2. Confirm the account is **Email-verified** (Settings → Account → verify email).
3. Confirm the API token is active and was created by that account (Settings → API → "Create New Token" to regenerate).
4. On the **M5 competition page** (`kaggle.com/competitions/m5-forecasting-accuracy`), click **"Join" / "Accept Rules"** — competition data is only downloadable after accepting the rules.
5. Verify a plain dataset download works: `kaggle datasets download -d olliekoonen/greenspace`. If this still returns `datasets.get was denied`, the token itself lacks scope — regenerate a new token and retry.

Alternatively, download the M5 files **manually in a browser** from the Kaggle competition Data tab (authenticated session), and place the five CSVs directly into `data/raw/` (kept unchanged).
- Acquisition procedure (reproducible): `scripts/acquire_m5.py` downloads the competition zip, extracts the raw CSVs **unchanged** into `data/raw/`, and writes a provenance `data/raw/MANIFEST.json` (checksums + sizes + source).
- Profiling: `scripts/python/profile_m5.py`; validation: `scripts/python/validate_m5.py`; diagnostic charts: `scripts/python/diagnose_m5.py`; data-quality tests: `tests/data/test_m5_quality.py`.

### Required credential action (user-provided)

Provide one of the following (never committed; read at runtime only):
1. **`kaggle.json`** at `%USERPROFILE%\.kaggle\kaggle.json` containing:
   `{ "username": "<your-username>", "key": "<your-api-token>" }`
   (obtained from *kaggle.com → Account → Create API Token*), **or**
2. **Environment variables** `KAGGLE_USERNAME` and `KAGGLE_KEY`.

Once credentials are in place, run from the repo root:
```
.venv\Scripts\python scripts\acquire_m5.py
.venv\Scripts\python scripts\python\profile_m5.py
.venv\Scripts\python scripts\python\validate_m5.py
.venv\Scripts\python scripts\python\diagnose_m5.py
.venv\Scripts\python -m pytest tests/data -q
```
Phase 1 completes after these run successfully and the data-quality report
under `reports/` is generated. Raw files are preserved unchanged.

### Provenance rules reaffirmed for Phase 1
- OBSERVED: raw M5 fields only (stored unchanged under `data/raw/`).
- DERIVED: profiling/statistics computed from observed data (reports, processed outputs).
- SIMULATED: **NOT created in Phase 1** (reserved for inventory/supply-chain phases).
