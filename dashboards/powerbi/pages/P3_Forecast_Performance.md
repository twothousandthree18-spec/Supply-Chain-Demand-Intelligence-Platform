# Page 3 — Forecast Performance

**Intent:** Quantify forecast accuracy and model selection, and inspect the final 28-day forecast. All
forecast/evaluation content is **derived** (not simulated). Critical validity rule: **ETS/SARIMA were
evaluated only on a 64-series pilot** — never present a cross-model aggregate that implies full 30,490-series
support.

**Primary sources:** `FactForecastEvaluation` (122,088), `FactForecast` (final 853,720), `DimModel` (6),
`DimProduct/DimStore/DimDepartment/DimCategory`, `DimDate`.

---

## Accuracy cards (V1–V5)
| # | Visual | Measure | Note |
|---|--------|---------|------|
| V1 | WMAE | `Forecast WMAE` | demand-weighted; support nuance below |
| V2 | WRMSE | `Forecast WRMSE` | demand-weighted |
| V3 | MAE | `Forecast MAE` | mean absolute |
| V4 | RMSE | `Forecast RMSE` | |
| V5 | Bias | `Forecast Bias` | + = over-forecast; tooltip explains sign |

- **Provenance:** derived on all.
- **Undefined:** BLANK → "—".

### Support rule (locked — do not weaken)
- `FactForecastEvaluation` has **122,088** rows: models 1–4 evaluated on all **30,490** series; models 5–6
  (ETS/SARIMA) on the **64**-series pilot only.
- **A cross-model "overall accuracy" card is only valid on the common pilot (64 series).** Implementation:
  - Add a small `[Common Pilot Only]` toggle (default OFF).
  - When ON: filter `FactForecastEvaluation` to the 64 common pilot series; all model cards + V6–V8 are valid
    across all 6 models.
  - When OFF: accuracy cards that read individual **selected model** are fine (pick a model from `DimModel`
    slicer); never present ETS/SARIMA as having full support in an aggregate.
- V1–V5 default to the **selected model** (via `DimModel` slicer) to avoid an invalid cross-model aggregate.

## Accuracy by hierarchy (V6–V8)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V6 | WMAE by department | `Forecast WMAE` | `DimDepartment[dept_name]` | Bar |
| V7 | WMAE by store | `Forecast WMAE` | `DimStore[store_id]` | Bar |
| V8 | WMAE by model family | `Forecast WMAE` | `DimModel[model_family]` | Bar |

- **V8 support nuance:** by-model-family bars must respect the pilot rule — a model family spanning
  ETS/SARIMA only plots the 64-series pilot values; label the axis with its support (e.g., "ETS (pilot 64)").
- **Bias heatmap (V9):** `Forecast Bias` by `dept × store` (colour −/0/+), derived.

## Model selection (V10)
- **Visual:** pie/bar of `Series Count` per `DimModel[model_name]` where `is_selected=TRUE`.
- **Note (locked):** `model_registry.is_selected = naive`; all 30,490 series' final forecast is the naive model.
  (Fact: `fact_forecast.is_final` = 30,490×28 from exactly one producing model per series-day; model_id on the
  final rows is the producing model — 1:1, no fan-out.)
- **Handle:** V10 also can show producing-model mix from `FactForecast[model_id]` if desired, but the canonical
  "selected model" is naive.

## Final forecast vs actual (V11)
- **Visual:** line (forecast) + scatter/points (observed actual last 14 days if present in the bounded series)
  by `DimDate[calendar_date]` over the 28-day horizon (date_id 1942..1969) for a **single selected series**.
- **Measures/fields:** `forecast_value` (line), `lower_bound`/`upper_bound` (confidence band),
  `FactForecast[model_id]→model_name`.
- **Interaction:** a series-selection (product + store slicer) drives V11.
- **Provenance:** derived (forecast) — observed actual is only available via the bounded dimension; do NOT
  pull the 59M observed fact.

---

## Filters / interactions (P3)
- **Slicers:** model family + `is_selected`, department, category, store, product (for V11), `[Common Pilot
  Only]` toggle.
- **Cross-filter:** selecting a department/store slices V6–V9 and V11; a model slices accuracy cards + V8.
- **Drill-downs:** product→store→(series) for V11.
- **Tooltips:** forecast_value, lower/upper bounds, model_name, `ProvenanceLabel` (derived), support count.

## Empty / undefined states
- Where a measure is undefined → "—".
- Model with no evaluation rows (e.g., ETS filtered to a non-pilot store) shows an empty category label
  (not zero) — support-aware.
- V11 shows a placeholder prompting to select a series if none selected.

## Business interpretation
- WMAE/errors tell which forecasts to trust for inventory sizing.
- Bias sign: sustained over-forecast → over-buy/excess; under-forecast → stockout risk.
- Final forecast line (V11) is the steer for a planner inspecting an individual product/store.

## Accessibility / readability
- Confidence band translucent + labelled; bias heat uses diverging red-white-green with numeric labels.
- Model labels include support count ("naive (30,490)", "ETS (pilot 64)") when shown aggregated.
- Data titles + one-line caption; arrows/icons paired with colour for bias sign.

---

## Validation (bound to this page)
- V1–V5 reconcile to `FactForecastEvaluation` WMAE/WRMSE/MAE/RMSE/bias for the selected model (traceability §C).
- V11 grain = 28-day horizon 1942..1969, one producing `model_id` per (series,date).
- **Pilot rule enforced:** no visual presents ETS/SARIMA as 30,490 series; cross-model aggregates require the
  Common Pilot toggle.
- Provenance derived on all forecast content; no `fact_daily_sales`.