# Page 2 — Demand Overview

**Intent:** Characterize demand patterns to inform forecasting/inventory judgement — trend, growth,
volatility, segmentation (volume×volatility risk matrix), seasonality and day-of-week profile. Reads the
30,490 series once, never the raw daily fact.

**Primary sources:** `FactDemandAnalysis` (30,490), `FactDemandSeasonality` (359,181),
`FactDemandSeasonalityDow` (168), `DimProduct/DimStore/DimCategory/DimDepartment`.

---

## Distribution & segmentation (V1–V5)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V1 | Trend direction split | `Series Count` | `FactDemandAnalysis[trend_direction]` | Bar (increasing/flat/decreasing) |
| V2 | CV distribution | `Series Count` | `FactDemandAnalysis[cv]` (binned) | Histogram |
| V3 | Volatility class | `Series Count` | `segment_volatility` (Low/Medium/High) | Donut |
| V4 | Demand pattern | `Series Count` | `segment_demand` (Smooth/Erratic/Lumpy/Intermittent) | Bar |
| V5 | Volume×Volatility risk matrix | `Series Count` | matrix rows `segment_volume` × cols `segment_volatility` | Heat/matrix |

- **V5 flyout:** show `risk_category` (Critical/High/Moderate/Low) — derived from `risk_cell`/`risk_category`
  columns (already stored; not computed).
- **Top-N:** none (aggregates over all series).

## Trend & growth (V6–V8)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V6 | Demand growth rate | `AVG(demand_growth_rate)` (demand-weighted via measure not to be confused with additive) | `demand_growth_rate`, `growth_is_defined` | Bar by category/dept |
| V7 | Trend effect | `AVG(trend_effect_pct)` | `trend_effect_pct` (None-tolerant) | Bar by category |
| V8 | Growth defined vs zero-base | `Series Count` split `growth_is_defined`/`growth_denominator_zero` | | Stacked bar |

- **Undefined:** V6/V7 use `AVG` of stored percent; when a row has undefined value the numerator counts
  `0` but it renders via `AVG` with NULL-tolerant handling -> show "—" only when the entire selection is
  undefined (per shared §4).

## Seasonality (V9–V12)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V9 | Seasonality strength | `AVG(seasonality_strength)` (only where `has_meaningful_seasonality`) | `seasonality_strength` | Bar by category |
| V10 | Peak month distribution | `Series Count` by `peak_month` | `peak_month` | Bar (monthly axis) |
| V11 | Trough month distribution | `Series Count` by `trough_month` | `trough_month` | Bar |
| V12 | Seasonal index curve | `AVG(seasonality_index)` | `DimDate[month]` (role) | Line |

- **V12 grain:** `FactDemandSeasonality` monthly indices joined to `DimDate[month]`; **provenance derived**.

## Day-of-week profile (V13)
- **Visual:** line of `AVG(dow_index)` by `DimDate[weekday_num]` from `FactDemandSeasonalityDow`.
- **Scope filter (page-level):** `scope_type`/`scope_value` (all / category / dept / store / state) — a
  `scope` slicer. Default "all".
- **Provenance:** derived.

---

## Filters / interactions (P2)
- **Slicers:** department, category, store, state; `dow_scope` (for V13); segment (volume/volatility/pattern).
- **Cross-filter:** choosing a risk-matrix cell (V5) filters V1–V4, V6–V8 (shows that cell's profile).
- **Drill-downs:** department→category→product; store→state.
- **Tooltips:** provenance; counts with % shares; a "risk category" tag (V5).

## Empty / undefined states
- A series with `cv=None` is treated as **High** volatility (conservative) — count lands in High (per
  `segment_volatility` rule), not dropped.
- `growth_denominator_zero` series show in the "zero-base (undefined)" bucket, never fabricated as −100%.
- `AVG(trend_effect_pct)` returns blank where no meaningful trend → "—" per selection.

## Business interpretation
- V1: trend direction mix tells if demand is broadly rising/falling.
- V5: the volume×volatility matrix is THE triage for where to prioritize (high-volume+high-volatility).
- V12/V13: seasonal/DOW shape informs whether forecasting must model seasonality (most series are meaningful).
- Segment counts over the 30,490 series reconcile to 30,490 on uncut views.

## Accessibility / readability
- Histograms have 8–16 bins with explicit bin width; gridlines at ~16.
- Risk-matrix heat uses the tier palette (Critical dark red → Low green) with count labels (colour + number).
- Axis labels ≥ 11pt; captions describe the decision to draw from each visual.

---

## Validation (bound to this page)
- V5 counts over a full view sum to 30,490 (= `Series Count` over all `FactDemandAnalysis`).
- V13 reads `FactDemandSeasonalityDow` and respects the `scope` filter (all/category/dept/store/state).
- Provenance derived on all visuals.
- No `fact_daily_sales`.