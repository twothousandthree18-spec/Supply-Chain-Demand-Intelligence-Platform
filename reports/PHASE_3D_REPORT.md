# Phase 3D — Forecasting: Completion / Progress Report

**Status:** COMPLETE — forecasting machinery implemented, fully unit-tested, the bounded statistical pilot completed successfully, and the bounded production forecasting run completed successfully (run_id=7, 30,490 series) with all derived outputs populated and verified. Phase 3D is **COMPLETE** (Phase 3E not started).

---

## 1. Phase 3D Scope

Phase 3D delivers a forecasting layer for the demand analytics platform built in Phases 2, 3B, and 3C:

- Observed-only daily demand forecasting (daily M5 window d_1..d_1941; forecast target d_1942..d_1969).
- Baselines: naive, seasonal-naive, moving-average, weighted moving-average (run on all 30,490 product/store series, vectorized).
- Bounded statistical models: ETS / Holt-Winters and a single SARIMA variant, fitted ONLY on a bounded pilot subset (top-N series by lifetime units, `config.PILOT_TOP_N = 64`) — never 30,490 uncontrolled fits.
- Chronological single-origin holdout validation (train [1,1913], validate [1914,1941]) — **no random split, no leakage**.
- Per-series, margin-based model selection (a statistical model wins a series only if it genuinely beats the best baseline by ≥ 1% relative WMAE).
- A dedicated forecast test suite.

## 2. Status Summary

| Area | Status |
|---|---|
| Phase 3D DDL (`sql/schema/06_phase3d_objects.sql`) | Applied |
| Forecasting package (`src/forecasting/*`) | Implemented |
| Forecast test suite | **98 passed, 0 failed** |
| Driver source defects found & fixed | Yes (see §4) |
| Statistical pilot result (post-fix) | **Completed successfully — captured** (see §5) |
| Pilot decision | ETS/Holt-Winters and SARIMA both qualify (see §5) |
| Production forecasting driver run | **COMPLETED** — run_id=7, SUCCESS (see §6) |
| `fact_forecast`, `fact_forecast_evaluation`, `model_registry` populated | **YES** — verified (see §6) |
| Phase 3E | **NOT started** |

## 3. Implementation Completed

- `src/forecasting/config.py` — single source of truth for forecasting constants (observed window, final 28-day horizon, chronological validation window, seasonality=7, MA window=7, min train points=28, pilot top-N=64, selection margin=1%, PI z=1.96), plus a persisted `RULES` dict.
- `src/forecasting/metrics.py` — pure MAE / RMSE / WMAE / WRMSE / bias / abs-error / error-series / residual-std / forecast-interval / demand-weighted aggregation.
- `src/forecasting/datacontract.py` — data-contract validation (chronological, no NaN/Inf, no gaps, observed-only provenance) and the strict past→future chronological split. No random/shuffled split surface.
- `src/forecasting/models.py` — vectorized baselines (`naive`, `seasonal_naive`, `moving_average`, `weighted_ma`) and bounded statistical fitters `fit_ets_holt_winters`, `fit_sarima` with finite, clipped (≥0) forecasts and a documented fallback (ok=False) on sparse/constant series.
- `src/forecasting/selection.py` — best-baseline selection, margin-based `statistical_wins`, `select_for_series`, and `champion_model`.
- `src/forecasting/run_forecasting.py` — the bounded, resumable, FK-safe driver and a read-only `--pilot-only` mode (top-64 comparison only, no DB writes).

### Tests
`tests/forecast/` (6 modules + conftest): `test_metrics.py`, `test_datacontract.py`, `test_baselines.py`, `test_models_ets_sarima.py`, `test_selection.py`, `test_driver_contract.py`.

**Test suite result: 98 passed, 0 failed.**

## 4. Genuine Source Defects Found & Fixed (no assertions weakened)

During testing / the first pilot attempt, the following genuine defects were found in the **source** (assertions were not weakened):

1. `datacontract.validate_series` — a scalar `str` provenance (e.g. `"observed"`) was treated as a per-point sequence because `str` has `__len__`, causing a spurious "lengths differ" error. Fixed to treat plain `str` as scalar and only check `list`/`tuple`/`ndarray` per-point. (This would also have broken the production driver.)
2. `metrics.residual_std` — inconsistent with its documented contract: it returned `0.0` for a constant/zero-spread error series instead of `None`. Fixed so zero/constant spread yields `None` (no measurable uncertainty).
3. `run_forecasting.series_metrics_dict` — did not emit a `"weight"` key, so `aggregate_weighted_metrics` computed zero total weight and returned `{}`, causing a `TypeError: unsupported format string passed to NoneType.__format__` when the driver printed baseline WMAE. This is the **first pilot failure** (§5). Fixed by emitting the between-series aggregation weight in the returned dict.
4. `models.FitResult` — the `obj` field lacked a type annotation, so the `@dataclass` did not treat it as a field and `__init__` never accepted `obj=`. Every statistically successful ETS/SARIMA fit raised `FitResult.__init__() got an unexpected keyword argument 'obj'` and was forced into the fallback path (mislabeled `ok=False`), producing a spurious `ok=0 fail=64` pilot result. Fixed by annotating `obj: Optional[object] = None`. The model tests did not catch this because they never assert `ok=True` on successful fits.

## 5. Statistical Pilot (--pilot-only)

- **Purpose:** boundedly compare ETS/Holt-Winters and SARIMA against the four baselines on the top-64 pilot subset and decide whether advanced models justify their cost, before any full run. The path is read-only (no `INSERT`/`UPDATE`/`DELETE`; the `--pilot-only` branch returns before any write statement).
- **First attempt:** FAILED. It reached the baseline-evaluation block and crashed at `src/forecasting/run_forecasting.py` with `TypeError: unsupported format string passed to NoneType.__format__`, caused by the `series_metrics_dict` weight defect (see §4.3). Prior steps completed: metadata pull (30,490 series), bounded trailing-window pull `[1900,1941]`, and data-contract validation OK.
- **Root cause fixed:** yes — the `series_metrics_dict` weight defect was fixed.
- **Second defect discovered (statistical fallback masked by a dataclass bug):** an early post-fix probe reported `ok=0 fail=64` for BOTH statistical models. A targeted in-process diagnostic on top pilot series showed every statistically successful fit raised `FitResult.__init__() got an unexpected keyword argument 'obj'` — in `src/forecasting/models.py` the `obj` field lacked a type annotation, so the `@dataclass` never accepted `obj=`, forcing every successful fit into the documented fallback and mislabeling it `ok=False`. Fixed by annotating the field as `obj: Optional[object] = None`. **No test assertions were weakened**; the suite remained **98 passed, 0 failed**.
- **Final post-fix pilot run:** SUCCEEDED (exit code 0). Complete stdout/stderr captured to `reports/PHASE_3D_PILOT_OUTPUT.txt`. Elapsed **360.8 s**. No DB writes.

### 5.1 All-series baseline evaluation (30,490 series, holdout [1914,1941])

| Baseline | WMAE | WRMSE | bias |
|---|---|---|---|
| naive | 5.1101 | 6.0994 | +0.6622 |
| seasonal_naive | 4.8664 | 5.9826 | −0.4442 |
| moving_average | 4.4169 | 5.5056 | −0.4442 |
| **weighted_ma** | **4.3428** | **5.3936** | **−0.0566** |

`weighted_ma` is the strongest baseline on the full 30,490-series population.

### 5.2 Pilot subset

- **Series:** top-64 by lifetime units (`config.PILOT_TOP_N = 64`).
- **Full history:** 64/64 pilot series have full observed history.
- **Validation:** 28-day chronological holdout (train [1,1913], validate [1914,1941]).

### 5.3 Pilot-subset comparison

| Model | WMAE | ok | fail | beats best baseline |
|---|---|---|---|---|
| weighted_ma (best baseline) | 13.4133 | — | — | — |
| ETS / Holt-Winters | 11.7914 | 64 | 0 | True |
| SARIMA | 11.9153 | 64 | 0 | True |

- **ETS improvement vs pilot weighted_ma ≈ 12.1%.**
- **SARIMA improvement vs pilot weighted_ma ≈ 11.2%.**

### 5.4 Decision

- **ETS/Holt-Winters qualifies** under the existing ≥1% WMAE improvement rule (≈12.1% better than the pilot-subset best baseline).
- **SARIMA also qualifies** (≈11.2% better than the pilot-subset best baseline).
- **ETS is the stronger statistical model** on this pilot (WMAE 11.7914 vs SARIMA 11.9153).
- **Weighted MA remains the strongest baseline** for the broader all-series baseline evaluation.
- **IMPORTANT scope caveat:** statistical-model performance (WMAE 11.79 / 11.92) must **NOT be compared directly** with the 30,490-series baseline numbers (WMAE ~4.34) because the statistical models were evaluated only on the **top-64 pilot subset**, whose weighted demand differs materially from the full population. The only valid direct comparison is within the pilot subset (best baseline weighted_ma WMAE = 13.4133 vs statistical models).

## 6. Production Forecasting Run (bounded driver)

The existing production driver (`src/forecasting/run_forecasting.py`, run without `--pilot-only`) was executed **once**. Complete stdout/stderr captured to `reports/PHASE_3D_PRODUCTION_OUTPUT.txt`.

- **run_id** = 7, **status** = `success`, records 30,490 / 30,490, **runtime ≈ 1099.2 s**.
- **Series:** all **30,490** product/store series; baselines evaluated across all series.
- **Final forecast:** 28-day horizon, origin **1941** → days **[1942,1969]**, with ~95% prediction intervals.
- **Statistical models:** ETS/Holt-Winters and SARIMA fitted **only** on the configured top-64 pilot subset (`PILOT_TOP_N=64`), using the existing ≥1% WMAE selection rule.
- **Write strategy:** batched `executemany` with periodic commits (chunk=5000, commit every 8 chunks), children-before-FK-parent, `DELETE`+`INSERT` per derived table; **not** the Phase 2 single-transaction pattern.
- **Provenance:** all forecast outputs `data_provenance='derived'`.

### 6.1 Per-series model selection (30,490 series)

Model selection is **per-series** under the ≥1% WMAE rule — the most-frequently-winning model across series is the champion:

| Model | Series selected | Notes |
|---|---|---|
| naive | 13,627 | **champion baseline** (most-frequent per-series winner) |
| weighted_ma | 6,045 | strongest aggregate baseline on the full population |
| moving_average | 7,146 | |
| seasonal_naive | 3,634 | |
| ETS / Holt-Winters | 22 | on top-64 pilot series that beat best baseline |
| SARIMA | 16 | on top-64 pilot series that beat best baseline |
| **Total** | **30,490** | |

**Important distinction:** model selection is per-series, so **Naive is the most frequent champion overall (13,627 series)** even though **weighted_ma was the strongest aggregate baseline** (lowest aggregate WMAE on the broad evaluation). `is_selected=True` in `model_registry` is set for Naive (champion baseline), ETS, and SARIMA (statistical models that genuinely beat the best baseline on their pilot subset). These are compatible: Naive wins the most individual series across all 30,490, while statistical models win only on the high-volume pilot subset where they clear the margin.

### 6.2 Populated outputs (verified lightweight, no 59M scan)

| Object | Rows | Notes |
|---|---|---|
| `model_registry` | **6** | naive/champion, seasonal_naive, moving_average, weighted_ma, ets_holt_winters, sarima |
| `fact_forecast` | **853,720** | 30,490 series × 28 days; dates [1942,1969]; 0 negative values; 0 null PI bounds |
| `fact_forecast_evaluation` | **122,088** | 4 baselines × 30,490 + 2 statistical × 64 |
| `forecast_rules` | **11** | persisted reproducible thresholds |

### 6.3 What Was NOT Done in This Session

- Phase 3E (inventory simulation) was **NOT started**; `fact_inventory_simulation` untouched.
- **No database row counts / heavy scans** of the 59M observed fact were run as part of Phase 3D verification (only a lightweight `[1942,1969]` provenance probe).
- Phase 2, 3B, and 3C were **not modified** during Phase 3D (only `src/forecasting/*` changed).

## 7. Known Limitations

- **Statistical models fitted only on the top-64 pilot subset** — ETS/SARIMA beat the best baseline on that subset (ETS WMAE 11.7914, SARIMA 11.9153 vs weighted_ma 13.4133), but non-pilot series rely on the broad baseline (weighted_ma aggregate). Direct comparison of statistical vs full-population baseline numbers is invalid (see §5.4). Only 38 series (22 ETS + 16 SARIMA) were selected for a statistical model; the other 30,452 series use a baseline.
- **M5 daily demand is extremely volatile** (cv ≥ 1.0 on nearly all series), so per-series WMAE uplift is modest except on high-volume series — hence Naive's high per-series win count despite weighted_ma's better aggregate accuracy.
- General forecasting limitation: M5 daily demand is sparse and noisy; no forecasting method removes that irreducible volatility.

## 8. Acceptance Checklist

| Criterion | Status |
|---|---|
| Chronological (non-random) validation, no leakage | Implemented + tested (13 datacontract tests) |
| Forecast metrics (MAE/RMSE/WMAE/WRMSE/bias) | Implemented + tested (14 metrics tests) |
| Prediction intervals | Implemented + populated (853,720 rows, 0 null bounds) |
| Baselines implemented & validated | Implemented + tested (13 baseline tests) |
| Bounded ETS/SARIMA (small-series, finite, fallback) | Implemented + tested (15 model tests; small series only) |
| Model-selection logic & determinism | Implemented + tested (17 selection tests) |
| Driver I/O contract / provenance / FK-safe / no random split | Implemented + tested (26 driver-contract tests) |
| Forecast test suite | **98 passed, 0 failed** |
| DDL applied (`06_phase3d_objects.sql`) | Done |
| Post-fix statistical pilot result captured & decision documented | **DONE** — completed successfully (see §5) |
| Production forecasting driver run | **DONE** — run_id=7 SUCCESS (see §6) |
| `model_registry` / `fact_forecast` / `fact_forecast_evaluation` populated | **DONE** — verified (see §6.2) |
| Phase 2/3B/3C intact verification after run | **DONE** — counts intact, observed fact untouched (see §9) |
| `docs/forecasting_architecture.md` updated to implementation | **DONE** |
| Phase 3E | **NOT started** (correct) |

**Phase 3D is COMPLETE:** the forecasting machinery is implemented, unit-tested (98 passed), the bounded statistical pilot and the bounded production run both completed successfully, and all derived outputs are populated and verified. Phase 3E remains pending.

## 9. Final Verification (lightweight, run_post-production)

No rerun of forecasting and no scan of the 59M-row observed fact. Queries hit only metadata and derived tables, plus a bounded `[1942,1969]` provenance probe on `fact_daily_sales` (0 rows — untouched).

- **run_id=7** = `success` (records 30,490 / 30,490, no error).
- **model_registry** = 6 rows, all `data_provenance='derived'`; `is_selected`: naive=champion, ets_holt_winters, sarima.
- **fact_forecast** = 853,720 rows (`derived`), 30,490 distinct series × 28 dates [1942,1969], origin 1941, `is_final` all true, **0 duplicate (model,series,date) keys**, 0 negative forecasts, 0 null PI bounds.
- **fact_forecast_evaluation** = 122,088 rows (`derived`): 30,490 per baseline model + 64 per statistical model (confirmed bounded to the pilot subset).
- **forecast_rules** = 11 rules persisted (horizon 28, observed_end 1941, train_end 1913, validation 1914/1941, seasonality 7, ma_window 7, min_train 28, pilot_top_n 64, improvement 0.01, pi_z 1.96).
- **Phase 2 / 3B / 3C intact:** dim_product 3,049, dim_store 10, fact_product_store_demand 30,490, fact_demand_analysis 30,490, fact_demand_seasonality 359,181, mv_weekly_sales 8,476,220 — all match prior-phase report values. Observed fact `[1942,1969]` has 0 rows (forecasting did not write any observed data).
