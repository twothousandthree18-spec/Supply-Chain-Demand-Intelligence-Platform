# Demand Analysis (Phase 3C)

**Status:** implemented
**Driver:** `src/analytics/run_demand_analysis.py`
**Pure metric functions:** `src/analytics/metrics.py`
**Thresholds:** `src/analytics/config.py` (+ persisted to `demand_analysis_rules`)
**Tests:** `tests/python/test_demand_analysis.py`, `tests/sql/test_phase3c_demand_analysis.py`

This phase derives product/store demand-analysis metrics from the **Phase 3B
materialized layer** (`mv_weekly_sales`, `fact_product_store_demand`) plus a single
bounded day-of-week aggregation. It never re-scans `fact_daily_sales` more than once
and never in a Python loop. All outputs are `data_provenance = 'derived'` and every
metric has one canonical, tested definition.

---

## Reused Phase 3B inputs (never recomputed in Python)

| Input | Use |
|---|---|
| `fact_product_store_demand` | per-series mean/std/CV (daily grain), zero-demand days, OLS trend slope |
| `mv_weekly_sales` + `dim_date` | per-series weekly aggregates for recent/prior growth and monthly seasonality |
| `fact_daily_sales` (ONE aggregation only) | aggregate day-of-week seasonal factors |

---

## Metrics & formulas

### 1. Volatility (CV)
```
cv = stddev(units_sold) / mean(units_sold)        # daily grain, Phase 3B
```
`cv` is `NULL` when `mean ≈ 0` (a zero series has no CV). A constant non-zero series
has `cv = 0`.

### 2. Trend
Phase 3B computes the OLS slope `trend_slope = REGR_SLOPE(units_sold, date_id)`. Trend
**direction** uses the normalized relative effect of that slope across the series:
```
trend_effect_pct = trend_slope * span_days / max(mean_daily_units, EPSILON) * 100
```
| Condition | Direction |
|---|---|
| `effect_pct >= +10` | `increasing` |
| `effect_pct <= -10` | `decreasing` |
| otherwise (or span < 30, or mean ~ 0) | `flat` |

A direction is only emitted when the series is long enough and non-zero; otherwise it
is `flat` (no manufactured trend).

### 3. Growth (recent vs prior) — zero-denominator guarded
Growth compares the last 4 active weeks against the 4 weeks before them (weekly grain,
bounded, single SQL pass):
```
recent_4wk_mean = AVG(units) over the last 4 active weeks per series
prior_4wk_mean  = AVG(units) over weeks 5..8 from the end
demand_growth_rate = recent_4wk_mean / prior_4wk_mean - 1     (when prior_4wk_mean > 0)
```
**Guard:** if `prior_4wk_mean <= 1e-9` (no prior demand), `demand_growth_rate = NULL`,
`growth_is_defined = FALSE`, `growth_denominator_zero = TRUE`. A percentage change from
a zero (or near-zero) base is meaningless and is never manufactured.

### 4. Calendar seasonality (month-of-year)
From per-series monthly mean weekly units (single SQL pass over `mv_weekly_sales`):
```
seasonality_index(month) = month_mean_weekly / overall_mean_weekly      # overall mean
                            = simple mean of the active months' weekly means
seasonality_strength = CV(seasonality_index)                          # spread around 1.0
peak_month / trough_month = argmax / argmin seasonality_index
```
A series is flagged `has_meaningful_seasonality = TRUE` only when it has at least
`season_min_active_months = 10` active months **and** a positive, finite strength. Sparse
or flat series are **not** flagged — we do not manufacture seasonality the data does not
support. Only meaningful series are persisted to `fact_demand_seasonality`.

### 5. Day-of-week (weekly) seasonality
Aggregate day-of-week factors computed from a **single** scan of `fact_daily_sales`
grouped by (store, category, dept, state, weekday), collapsed to scopes
`all / store / state / category / dept`:
```
dow_index(dow) = mean_daily_units(dow) / overall_mean_daily_units      # within each scope
```
Factors center on 1.0 (weekdays < 1, weekends > 1 where present).

### 6. Segmentation

**Volume** (data-driven terciles over the 30,490 series; cut-points persisted):
| Level | Condition |
|---|---|
| `Low` | `total_units <= q33` |
| `Medium` | `q33 < total_units <= q67` |
| `High` | `total_units > q67` |

**Volatility** (documented CV thresholds):
| Level | Condition |
|---|---|
| `Low` | `cv < 0.50` |
| `Medium` | `0.50 <= cv < 1.00` |
| `High` | `cv >= 1.00` (or `cv is NULL`, conservative) |

**Demand pattern** (zero-demand ratio `= zero_demand_days / span_days`):
| Level | Condition |
|---|---|
| `Smooth` | `ratio < 0.50` |
| `Erratic` | `0.50 <= ratio < 0.75` |
| `Lumpy` | `0.75 <= ratio < 0.90` |
| `Intermittent` | `ratio >= 0.90` |

### 7. Volume × volatility risk matrix

```
risk_index = volume_rank * volatility_rank      # Low=1, Medium=2, High=3  (1..9)
```
| risk_index | Category |
|---|---|
| `>= 7` | `Critical` |
| `>= 4` | `High` |
| `>= 2` | `Moderate` |
| `else` | `Low` |

`High*High -> Critical`, `High*Medium / Medium*High -> High`, etc.

---

## Persisted objects (`data_provenance = 'derived'`)

| Object | Grain | Rows (approx) |
|---|---|---|
| `fact_demand_analysis` | product × store × window | 30,490 |
| `fact_demand_seasonality` | product × store × window × month (meaningful only) | ~359k |
| `fact_demand_seasonality_dow` | scope × weekday | ~168 |
| `demand_analysis_rules` | rule_key | 16 |

Run metadata is recorded in `etl_run_log` (`pipeline='demand_analysis'`); an
interrupted run is abandoned on the next invocation. The driver is idempotent
(DELETE-then-INSERT for the analysis window) and resumable.

## Known limitations
- Daily-grain `cv` for M5 is large for most series, so most products fall in the
  `High` volatility class (a documented property of sparse daily demand, not a bug).
- Calendar seasonality requires ≥ 10 active months; very sparse series are correctly
  excluded rather than given misleading seasonal factors.
- Growth is a simple recent-vs-prior 8-week comparison (baseline), not a fitted model.
