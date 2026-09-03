# Forecasting Architecture

**Phase 3D — Implemented & Production-Populated.** Forecast machinery is built, unit-tested (98 passed), the bounded statistical pilot completed, and the bounded production run (run_id=7) populated all derived forecast outputs. Phase 3E not started.

## 1. Purpose

Produce validated demand forecasts per product/store, and evaluate them honestly. Forecasting is evidence for inventory and decision layers — it must be statistically correct.

## 2. Phase 3D Workflow (implemented and run for production)

```
BASELINE (naive, seasonal-naive, MA, weighted-MA — all 30,490 series, vectorized)
   │
   ▼
BOUNDED STATISTICAL MODELS (ETS/Holt-Winters, SARIMA — top-64 pilot subset only)
   │
   ▼
CHRONOLOGICAL HOLD-OUT VALIDATION (train [1,1913], validate [1914,1941])
   │
   ▼
MODEL COMPARISON (WMAE / WRMSE / bias, weighted aggregation)
   │
   ▼
MARGIN-BASED PER-SERIES MODEL SELECTION (≥1% WMAE improvement rule)
   │
   ▼
FINAL FORECAST [1942,1969] + prediction intervals (origin 1941)
   │
   ▼
FORECAST EVALUATION (fact_forecast_evaluation) — populated
```

## 3. Stage Definitions

1. **BASELINE** — naive, seasonal-naive, moving/weighted moving average. These set the lower bound any smarter model must beat. **Implemented** on all 30,490 product/store series (vectorized numpy over a single bounded pull of the observed fact).
2. **CANDIDATE MODELS** — ETS / Holt-Winters (additive) and a single fixed SARIMA(0,1,1)×(0,1,1,7) variant. Fitted **only on the bounded top-64 pilot subset** (`config.PILOT_TOP_N = 64`) — never 30,490 uncontrolled fits. ML forecasting is out of scope for Phase 3D and is NOT assumed to win.
3. **TIME-BASED VALIDATION** — train on past, validate on future. Single-origin chronological holdout (train [1,1913], validate [1914,1941], 28 days), enforced by the data-contract layer. **Random train/test splitting is PROHIBITED** because it leaks future information and invalidates any time-series conclusion.
4. **MODEL COMPARISON** — compare on consistent accuracy metrics (WMAE, WRMSE, MAE, RMSE, bias) over the same validation window and entity set, with demand-weighted aggregation.
5. **MODEL SELECTION** — **per-series.** A statistical model wins an individual series only if it genuinely beats that series' best baseline by ≥1% relative WMAE (`config.SELECTION_IMPROVEMENT = 0.01`). A champion baseline is chosen by the most-frequently-selected model across series. A statistical model's `is_selected` in `model_registry` is set when it beats the best baseline over its pilot subset. Because selection is per-series, the most-frequent champion is NOT necessarily the model with the best aggregate WMAE.
6. **FINAL FORECAST** — re-fit the selected model to the full available history up to the forecast origin (1941) and produce the 28-day horizon forecast [1942,1969] with ~95% prediction intervals (z=1.96).
7. **FORECAST EVALUATION** — score the holdout forecast against realized values and log into `fact_forecast_evaluation`. This closes the loop and gives honest accuracy reported to stakeholders.

## 4. Models Considered (implemented candidate suite)

- Naive
- Seasonal naive (period 7)
- Moving / weighted moving average (window 7)
- Exponential smoothing — ETS / Holt-Winters additive
- SARIMA — fixed (0,1,1)×(0,1,1,7)

**Decision rule (implemented):** a more complex model is adopted only if it demonstrably improves validated accuracy by ≥1% WMAE. No technology for résumé value.

## 5. Phase 3D Pilot Results (actual, measured)

Bounded `--pilot-only` run, top-64 series by lifetime units, full history 64/64, 28-day chronological holdout, read-only (no DB writes). Complete output: `reports/PHASE_3D_PILOT_OUTPUT.txt`.

### 5.1 All-series baseline evaluation (30,490 series, holdout [1914,1941])

| Baseline | WMAE | WRMSE | bias |
|---|---|---|---|
| naive | 5.1101 | 6.0994 | +0.6622 |
| seasonal_naive | 4.8664 | 5.9826 | −0.4442 |
| moving_average | 4.4169 | 5.5056 | −0.4442 |
| **weighted_ma** | **4.3428** | **5.3936** | **−0.0566** |

`weighted_ma` is the strongest **aggregate** baseline on the full 30,490-series population.

### 5.2 Pilot subset comparison (top-64)

| Model | WMAE | ok | fail | beats best baseline |
|---|---|---|---|---|
| weighted_ma (best baseline) | 13.4133 | — | — | — |
| ETS / Holt-Winters | 11.7914 | 64 | 0 | True |
| SARIMA | 11.9153 | 64 | 0 | True |

- ETS improvement vs pilot weighted_ma ≈ **12.1%**.
- SARIMA improvement vs pilot weighted_ma ≈ **11.2%**.
- Elapsed time: **360.8 s**; exit code 0; no DB writes.

### 5.3 Pilot decision

- **ETS/Holt-Winters qualifies** under the ≥1% WMAE improvement rule.
- **SARIMA also qualifies.**
- **ETS is the stronger statistical model** on this pilot (WMAE 11.7914 < 11.9153).
- **Weighted MA remains the strongest aggregate baseline** for the broader all-series evaluation.
- **Scope caveat:** statistical-model performance must **NOT be compared directly** with the 30,490-series baseline numbers, because the statistical models were evaluated only on the **top-64 pilot subset**. The only valid direct comparison is within the pilot subset.

## 6. Phase 3D Production Run (actual, verified)

The bounded production driver was run once (run_id=7, status=success, records 30,490/30,490, ≈1099.2 s). Complete output: `reports/PHASE_3D_PRODUCTION_OUTPUT.txt`.

### 6.1 Production selection result (per-series, 30,490 series)

| Model | Series selected | Role |
|---|---|---|
| naive | 13,627 | **most-frequent per-series champion** |
| weighted_ma | 6,045 | strongest aggregate baseline |
| moving_average | 7,146 | baseline |
| seasonal_naive | 3,634 | baseline |
| ETS / Holt-Winters | 22 | statistical, pilot subset |
| SARIMA | 16 | statistical, pilot subset |
| **Total** | **30,490** | |

**Key distinction:** because selection is **per-series**, **Naive is the most frequent champion overall (13,627 series)** even though **weighted_ma had the strongest aggregate WMAE** (4.3428). These are different, both-correct statements: Naive wins the most individual series; weighted_ma is the best aggregated forecast across the population. Statistical models (ETS=22, SARIMA=16) were selected only on the top-64 pilot subset where they cleared the ≥1% margin.

### 6.2 Populated outputs

| Object | Rows | Notes |
|---|---|---|
| `model_registry` | 6 | naive (champion) + 3 baselines + ETS + SARIMA |
| `fact_forecast` | 853,720 | 30,490 × 28 days [1942,1969], origin 1941, PIs, `is_final` |
| `fact_forecast_evaluation` | 122,088 | 4 baselines × 30,490 + 2 statistical × 64 |
| `forecast_rules` | 11 | persisted reproducible thresholds |

All outputs `data_provenance='derived'`. Observed Phase 2 tables untouched (verified 0 rows in the forecast window). No duplicate forecast keys; no negative forecasts; no null interval bounds.

## 7. Forecasting Honesty Rules

- **No leakage:** features must never use future information (no future calendar at train time, no smoothing across the validation boundary).
- **Chronological validation:** always past→future; enforced by `datacontract.validate_series` and the strict split.
- **Reproducibility:** fixed orders/parameters, recorded params, code under version control, rules persisted to `forecast_rules`.
- **Uncertainty:** report prediction intervals, not just point forecasts, so inventory sizing can reflect risk.
- **Grain:** forecasts defined at product/store/day; rollups derived, not independently forecast (documented).
- **Provenance:** all forecast outputs are `data_provenance='derived'`; forecast tables are FK-safe and only touched by the forecasting driver.

## 8. Testing (Forecast layer)

`tests/forecast/` — leakage detection, chronological validation, reproducibility, and model-selection logic are first-class tests. **98 passed, 0 failed** (metrics, datacontract, baselines, ETS/SARIMA, selection, driver contract).
