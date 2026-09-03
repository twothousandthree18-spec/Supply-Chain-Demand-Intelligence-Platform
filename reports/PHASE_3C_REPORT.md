# Phase 3C Report — Demand Analysis

**Project:** Supply Chain & Demand Intelligence Platform
**Phase:** 3C — Demand Analysis (trend / seasonality / volatility / growth / segmentation / risk)
**Status:** ✅ **COMPLETE**
**Window:** `observed_full` (all series span `[1, 1941]` of `[1, 1969]`)
**Date:** 2026-08-30

---

## 1. Scope and status

Phase 3C converts the Phase 3B demand-stats layer (`fact_product_store_demand`) and the
Phase 3B materialized weekly layer (`mv_weekly_sales`) into a persisted, derived
product/store demand-analysis layer. It adds:

- Trend direction + normalized effect, volatility (CV), recent-vs-prior growth
- Calendar (month-of-year) seasonality and day-of-week seasonality
- Volume × volatility segmentation and a demand-pattern class
- A volume × volatility risk matrix (Critical / High / Moderate / Low)
- Documented, reproducible thresholds persisted to `demand_analysis_rules`

All inputs are `data_provenance='observed'` or Phase 3B derived; **all Phase 3C outputs
are `data_provenance='derived'`** and registered in `etl_run_log`.

Per the locked execution order, **Phase 3C does not perform forecasting, and Phase 3D was
NOT started.** `fact_forecast`, `fact_forecast_evaluation`, and `fact_inventory_simulation`
remain empty.

### Constraints honored
- Reuses `fact_product_store_demand` + the Phase 3B materialized layer; never rescans
  59M-row `fact_daily_sales` more than once (a single day-of-week aggregation), and never
  in a Python loop.
- No manufactured seasonality (only ≥ 10 active months, positive finite strength).
- Mathematically defensible formulas; explicit, reproducible thresholds/quantiles.
- Zero-denominator growth is guarded (`NULL`, never fabricated).
- Bounded/resumable driver (ONE scan of `fact_daily_sales`, single-pass aggregates over
  `mv_weekly_sales`).

---

## 2. Implemented demand metrics and formulas

All metric functions live in `src/analytics/metrics.py` (pure functions); thresholds live
in `src/analytics/config.py` and are persisted to `demand_analysis_rules`.

### 2.1 Volatility (coefficient of variation, CV)
```
cv = stddev(units_sold) / mean(units_sold)     # daily grain, computed in Phase 3B
```
- `cv = 0` for a constant non-zero series; `NULL` when `mean ≈ 0` (a zero series has no CV).

### 2.2 Trend
Phase 3B supplies the OLS slope `trend_slope = REGR_SLOPE(units_sold, date_id)`. Phase 3C
normalizes it to a relative effect across the full span:
```
trend_effect_pct = trend_slope * span_days / max(mean_daily_units, EPSILON) * 100
```
| Condition | `trend_direction` |
|---|---|
| `effect_pct >= +10` | `increasing` |
| `effect_pct <= -10` | `decreasing` |
| otherwise, or span < 30, or mean ~ 0 | `flat` |

Direction is only emitted when the series is long/non-zero; otherwise it is `flat` (no
manufactured trend).

### 2.3 Growth (recent vs. prior) with zero-denominator guard
Last 4 active weeks vs. the 4 weeks before them (weekly grain, single SQL pass over
`mv_weekly_sales`):
```
recent_4wk_mean = AVG(units) over last 4 active weeks per series
prior_4wk_mean  = AVG(units) over weeks 5..8 from the end
demand_growth_rate = recent_4wk_mean / prior_4wk_mean - 1     (only when prior_4wk_mean > 0)
```
**Guard:** if `prior_4wk_mean <= 1e-9` → `demand_growth_rate = NULL`,
`growth_is_defined = FALSE`, `growth_denominator_zero = TRUE`. A % change from a zero
(or near-zero) base is meaningless and is never manufactured.

### 2.4 Calendar seasonality (month-of-year)
Per-series monthly mean weekly units (single SQL pass over `mv_weekly_sales`):
```
seasonality_index(month) = month_mean_weekly / overall_mean_weekly
seasonality_strength     = CV(seasonality_index)          # spread around 1.0
peak_month               = argmax seasonality_index
trough_month             = argmin seasonality_index
```
A series is `has_meaningful_seasonality = TRUE` only with ≥ `season_min_active_months = 10`
active months **and** a positive, finite strength. Sparse/flat series are excluded — no
manufactured seasonality.

### 2.5 Day-of-week (weekly) seasonality
Aggregated from a **single scan** of `fact_daily_sales` grouped by
`(store, category, dept, state, weekday)`, collapsed to scopes
`all / store / state / category / dept`:
```
dow_index(dow) = mean_daily_units(dow) / overall_mean_daily_units     # within each scope
```
Factors center on 1.0. Global factors computed and persisted (see §9).

---

## 3. Segmentation and risk matrix

### 3.1 Volume (data-driven terciles over 30,490 series; cut-points persisted)
| Level | Condition |
|---|---|
| `Low` | `total_units <= q33` |
| `Medium` | `q33 < total_units <= q67` |
| `High` | `total_units > q67` |

### 3.2 Volatility
| Level | Condition |
|---|---|
| `Low` | `cv < 0.50` |
| `Medium` | `0.50 <= cv < 1.00` |
| `High` | `cv >= 1.00` (or `cv IS NULL`, conservative) |

### 3.3 Demand pattern (zero-demand ratio = `zero_demand_days / span_days`)
| Level | Condition |
|---|---|
| `Smooth` | `ratio < 0.50` |
| `Erratic` | `0.50 <= ratio < 0.75` |
| `Lumpy` | `0.75 <= ratio < 0.90` |
| `Intermittent` | `ratio >= 0.90` |

### 3.4 Risk matrix
```
risk_index = volume_rank * volatility_rank      # Low=1, Medium=2, High=3  (1..9)
```
| `risk_index` | Category |
|---|---|
| `>= 7` | `Critical` |
| `>= 4` | `High` |
| `>= 2` | `Moderate` |
| else | `Low` |

`High×High → Critical`, `High×Medium / Medium×High → High`, etc.

All 16 thresholds are persisted in `demand_analysis_rules` (`rule_key`, `rule_value`,
`description`, originating `config.py`).

---

## 4. Persisted database objects

Objects created by `sql/schema/05_phase3c_objects.sql` and populated by the
`run_demand_analysis.py` driver (all `data_provenance='derived'`):

| Object | Grain | Row count |
|---|---|---|
| `fact_demand_analysis` | product × store × window | **30,490** |
| `fact_demand_seasonality` | product × store × window × month | **359,181** |
| `fact_demand_seasonality_dow` | scope × weekday | **168** |
| `demand_analysis_rules` | rule_key | **16** |

`fact_demand_seasonality` holds only **meaningful** series: **30,048 / 30,490** series
flagged meaningful (442 sparse series correctly excluded).

---

## 5. Test results

### Python pure-function tests — `tests/python/test_demand_analysis.py`
**30 / 30 PASS** (~0.2s) — covers CV, growth (incl. zero-denominator), trend direction +
effect, seasonality meaningfulness/indices, volume/volatility segmentation, demand-pattern
classification, risk matrix, and DOW factors (incl. baseline-centered).

### SQL read-only integration tests — `tests/sql/test_phase3c_demand_analysis.py`
**17 / 17 PASS** — table existence/columns, populated counts, every demand-layer series has
an analysis row, units reconcile to observed, seasonality valid + within range, DOW ranges,
trend/risk domain values, volume terciles ~even, growth zero-denominator guard, finite
defined growth, rules persisted, run succeeded, Phase 2 intact.

### Full Phase 3A + 3B + 3C SQL suite
**76 / 76 PASS** — confirms the 3B analytical layer (32 tests) and 3A foundation (27 tests)
still pass alongside all 3C tests.

### Test fixes made this session (no assertions weakened)
1. `test_volume_terciles_roughly_even` used `scalar()` (first-column-only helper) on a
   3-column query → switched to `cursor.fetchone()`.
2. `test_phase3_tables_empty` (Phase 3A) still expected `fact_product_store_demand` to be
   empty, but Phase 3B intentionally populates it → introduced `PHASE3_TABLES_EMPTY`
   excluding that table; the other three Phase 3 fact tables (`fact_forecast`,
   `fact_forecast_evaluation`, `fact_inventory_simulation`) correctly remain empty.

---

## 6. Phase 2 preservation verification (rechecked this session)

| Object | Count | Intact? |
|---|---|---|
| `fact_daily_sales` | **59,181,090** | ✅ |
| `fact_weekly_price` | **6,841,121** | ✅ |
| Observed units (`sum(units_sold)`) | **66,927,173** | ✅ |

Phase 2 observed tables are untouched. The Phase 3C `sum(total_units)` also equals
**66,927,173**, fully reconciling the derived analysis layer to observed demand.

---

## 7. Execution / performance information

- Driver: `src/analytics/run_demand_analysis.py` (runs via `python -m src.analytics.run_demand_analysis`)
- Bounded: exactly **one** aggregation over `fact_daily_sales` (DOW) + single set-based
  aggregate passes over `mv_weekly_sales`; no Python-level row loops over the 59M table.
- ETL run log (`etl_run_log`):
  | run_id | pipeline | status | records |
  |---|---|---|---|
  | 4 | demand_analysis | **failed** (guarded/abandoned — `integer out of range`) | 0 / 0 |
  | 5 | demand_analysis | **success** | 30,490 / 30,490 |
  | 6 | demand_analysis | **success** | 30,490 / 30,490 |
- Driver wall time ~6m18s (run 6: 16:17:36 → 16:23:54).
- Idempotent (DELETE-then-INSERT for the analysis window) and resumable; an interrupted run
  is abandoned on the next invocation.

---

## 8. Key result summaries

| Metric | Result |
|---|---|
| Series analyzed | 30,490 |
| Demand volume terciles (Low/Med/High) | 10,167 / 10,160 / 10,163 |
| Volatility class (Low/Med/High) | 77 / 1,635 / **28,778** |
| Risk category (Low/Moderate/High/Critical) | 0 / 10,244 / 11,795 / 8,451 |
| Growth defined / zero-denominator-undefined | 29,073 / 1,417 |
| Trend direction (up / flat / down) | 19,590 / 1,718 / 9,182 |
| Meaningful seasonality series | 30,048 / 30,490 |
| Global DOW factors | Sat 1.210, Sun 1.198, Fri 0.996, Mon 0.957, Thu 0.879, Tue 0.885, Wed 0.874 |

---

## 9. Known limitations / warnings

1. **Volatility is mostly `High` (28,778 / 30,490).** Daily-grain CV ≥ 1.0 for nearly all M5
   series. This is a documented property of sparse daily demand, not a bug or manufactured
   result. Consequence: the risk matrix skews high, with 0 `Low` risk series.
2. **1,417 series have undefined growth** (zero/near-zero prior demand) — correctly `NULL`,
   never fabricated.
3. **442 series lack meaningful calendar seasonality** (fewer than 10 active months) — they
   are correctly excluded from `fact_demand_seasonality` rather than given misleading factors.
4. **Trend** is a linear baseline (OLS slope), not a fitted/flexible model.
5. **Growth** is a simple recent-vs-prior 8-week comparison (baseline), not a modeled forecast.

---

## 10. Acceptance-criteria checklist

| # | Criterion | Status |
|---|---|---|
| 1 | Uses `fact_product_store_demand` + Phase 3B materialized layer | ✅ |
| 2 | Does NOT repeatedly scan 59M-row `fact_daily_sales` (bounded, one DOW pass) | ✅ |
| 3 | No manufactured seasonality (≥10 active months, positive finite strength) | ✅ |
| 4 | Mathematically defensible formulas | ✅ |
| 5 | Explicit reproducible thresholds/quantiles (persisted in `demand_analysis_rules`) | ✅ |
| 6 | Zero-demand / intermittent series handled (demand-pattern classes + CV guard) | ✅ |
| 7 | Zero-denominator growth handled (NULL + flags, never fabricated) | ✅ |
| 8 | Bounded and resumable driver; ETL provenance `derived` + run log | ✅ |
| 9 | No forecasting / inventory simulation performed (those tables empty) | ✅ |
| 10 | Phase 3D NOT started; execution order respected | ✅ |
| 11 | Reports objects, results, tests, timing, warnings | ✅ |
| 12 | Phase 2 observed tables verified intact | ✅ |

---

## 11. Artifacts produced

- `sql/schema/05_phase3c_objects.sql` — Phase 3C DDL (applied)
- `src/analytics/config.py` — thresholds + risk matrix + 16 rules
- `src/analytics/metrics.py` — pure metric functions
- `src/analytics/run_demand_analysis.py` — bounded/resumable driver
- `docs/demand_analysis.md` — full formula/threshold documentation
- `tests/python/test_demand_analysis.py` (+ `tests/python/conftest.py`) — 30 unit tests
- `tests/sql/test_phase3c_demand_analysis.py` — 17 DB integration tests
