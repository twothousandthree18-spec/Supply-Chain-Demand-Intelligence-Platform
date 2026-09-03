"""
Supply Chain & Demand Intelligence Platform
Phase 3C - Demand analysis metric primitives (pure, DB-free).

Every function here is a deterministic transformation over plain Python/numpy
inputs, so it can be unit-tested without a database. The DB driver
(run_demand_analysis.py) feeds these the aggregates it pulls from the Phase 3B
materialized layer.

Definitions & thresholds: docs/demand_analysis.md and config.py
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import config


# --------------------------------------------------------------------------- #
# Volatility
# --------------------------------------------------------------------------- #
def compute_cv(values, epsilon: float = 1e-9) -> Optional[float]:
    """Coefficient of variation = std / mean. Returns None for ~zero-mean input.

    A zero (or constant-zero) series has no meaningful CV -> None.
    A constant non-zero series has CV = 0.
    """
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    if abs(mean) < epsilon:
        return None
    var = sum((v - mean) ** 2 for v in values) / n
    return (var ** 0.5) / abs(mean)


# --------------------------------------------------------------------------- #
# Growth (recent vs prior) with zero-denominator guard
# --------------------------------------------------------------------------- #
def compute_growth(
    recent_mean: float,
    prior_mean: float,
    epsilon: Optional[float] = None,
) -> Tuple[Optional[float], bool]:
    """Growth = recent_mean / prior_mean - 1.

    Returns `(rate, is_defined)`.
      * If prior_mean <= epsilon (zero/near-zero denominator, i.e. no prior
        demand) the percentage is meaningless -> (None, False). This avoids
        manufacturing a -100% (or infinite) figure from a zero base.
      * Otherwise returns (recent/prior - 1, True).
    """
    eps = config.GROWTH_EPSILON if epsilon is None else epsilon
    if prior_mean <= eps:
        return None, False
    return (recent_mean / prior_mean - 1.0), True


# --------------------------------------------------------------------------- #
# Trend direction (normalized OLS slope effect)
# --------------------------------------------------------------------------- #
def trend_direction(
    slope: float,
    span: int,
    mean: float,
    up_pct: Optional[float] = None,
    down_pct: Optional[float] = None,
    min_mean: Optional[float] = None,
    min_span: Optional[int] = None,
) -> str:
    """Classify trend from a linear-regression slope.

    effect_pct = slope * span / mean * 100  (approximate relative change across
    the series). Guards: if mean is ~0 or span too short, a slope carries no
    meaningful direction -> 'flat'.
    Returns 'increasing' | 'flat' | 'decreasing'.
    """
    up = config.TREND_UP_PCT if up_pct is None else up_pct
    down = config.TREND_DOWN_PCT if down_pct is None else down_pct
    mmean = config.TREND_MIN_MEAN if min_mean is None else min_mean
    mspan = config.TREND_MIN_SPAN if min_span is None else min_span
    if span < mspan or abs(mean) < mmean or slope is None:
        return "flat"
    effect_pct = slope * span / abs(mean) * 100.0
    if effect_pct >= up:
        return "increasing"
    if effect_pct <= down:
        return "decreasing"
    return "flat"


def trend_effect_pct(slope: float, span: int, mean: float) -> Optional[float]:
    """Relative slope effect as a percentage (None when not meaningful)."""
    if span < config.TREND_MIN_SPAN or abs(mean) < config.TREND_MIN_MEAN or slope is None:
        return None
    return slope * span / abs(mean) * 100.0


# --------------------------------------------------------------------------- #
# Segmentation: volume (terciles)
# --------------------------------------------------------------------------- #
def segment_volume(total_units: float, low_q: float, high_q: float) -> str:
    """Volume tercile: Low / Medium / High given data-driven quantile cuts."""
    if total_units <= low_q:
        return "Low"
    if total_units <= high_q:
        return "Medium"
    return "High"


# --------------------------------------------------------------------------- #
# Segmentation: volatility (CV)
# --------------------------------------------------------------------------- #
def segment_volatility(cv: Optional[float]) -> str:
    """Volatility class from CV with documented thresholds. None -> High (unmeasured
    volatility is treated conservatively as high for risk)."""
    if cv is None:
        return "High"
    if cv < config.CV_LOW:
        return "Low"
    if cv < config.CV_HIGH:
        return "Medium"
    return "High"


# --------------------------------------------------------------------------- #
# Segmentation: demand pattern (zero-demand ratio)
# --------------------------------------------------------------------------- #
def classify_demand(zero_ratio: Optional[float]) -> str:
    """Demand pattern from zero-demand ratio: Smooth/Erratic/Lumpy/Intermittent."""
    if zero_ratio is None:
        return "Intermittent"
    if zero_ratio < config.ZERO_RATIO_ERRATIC:
        return "Smooth"
    if zero_ratio < config.ZERO_RATIO_LUMPY:
        return "Erratic"
    if zero_ratio < config.ZERO_RATIO_INTERMITTENT:
        return "Lumpy"
    return "Intermittent"


# --------------------------------------------------------------------------- #
# Risk matrix (volume x volatility)
# --------------------------------------------------------------------------- #
def classify_risk(volume: str, volatility: str) -> Tuple[str, int]:
    """Risk cell + numeric risk index from volume and volatility classes.

    risk_index = volume_rank * volatility_rank (1..9), then mapped to a category.
    """
    vol_rank = config.VOLUME_LABELS.index(volume) + 1          # Low=1, Med=2, High=3
    vola_rank = config.VOLATILITY_RANK[volatility]              # Low=1, Med=2, High=3
    index = vol_rank * vola_rank
    cell = f"{volume}*{volatility}"
    if index >= config.RISK_CRITICAL:
        category = "Critical"
    elif index >= config.RISK_HIGH:
        category = "High"
    elif index >= config.RISK_MODERATE:
        category = "Moderate"
    else:
        category = "Low"
    return cell, index


def risk_category_from_index(index: float) -> str:
    """Map a numeric risk index to its category label."""
    if index >= config.RISK_CRITICAL:
        return "Critical"
    if index >= config.RISK_HIGH:
        return "High"
    if index >= config.RISK_MODERATE:
        return "Moderate"
    return "Low"


# --------------------------------------------------------------------------- #
# Calendar seasonality (month-of-year)
# --------------------------------------------------------------------------- #
def compute_seasonality(
    monthly_means: Dict[int, float],
    min_active_months: Optional[int] = None,
) -> Dict:
    """Compute month-of-year seasonality from a map of {month: mean_weekly_units}.

    Returns a dict:
      {
        'indices': {month: index},        # index = month_mean / overall_mean
        'strength': cv_of_indices | None,
        'peak_month': int | None,
        'trough_month': int | None,
        'n_active_months': int,
        'meaningful': bool,
      }

    overall_mean = simple mean of the supplied monthly means (each active month
    weighted equally; documented in docs/demand_analysis.md). A series is only
    flagged meaningful when it has enough active months (>= min_active_months),
    a finite, positive strength, and finite indices -- i.e. we do NOT manufacture
    seasonality for sparse series.
    """
    if min_active_months is None:
        min_active_months = config.SEASON_MIN_ACTIVE_MONTHS
    active = {m: v for m, v in monthly_means.items() if v is not None and v > 0}
    n_active = len(active)
    peak = trough = None
    strength = None
    indices: Dict[int, float] = {}
    meaningful = False

    if n_active > 0:
        overall = sum(active.values()) / n_active
        indices = {m: (v / overall) for m, v in active.items()}
        peak = max(indices, key=indices.get)
        trough = min(indices, key=indices.get)
        # strength = CV of the seasonal indices (spread around 1.0)
        strength = compute_cv(list(indices.values()))
        if (
            n_active >= min_active_months
            and strength is not None
            and strength > config.SEASON_MIN_STD
        ):
            meaningful = True

    return {
        "indices": indices,
        "strength": strength,
        "peak_month": peak,
        "trough_month": trough,
        "n_active_months": n_active,
        "meaningful": meaningful,
    }


# --------------------------------------------------------------------------- #
# Day-of-week factors (weekly pattern) - aggregate grouping helper
# --------------------------------------------------------------------------- #
def compute_dow_factors(mean_by_dow: Dict[int, float]) -> Dict[int, float]:
    """Day-of-week seasonal factors from {weekday_num: mean_daily_units}.

    factor(dow) = mean_daily(dow) / overall_mean_daily  (overall = mean of the 7
    day means; only days with data>0 are used). Returns all 7 values; days with
    no data are excluded from the factor set.
    """
    active = {d: v for d, v in mean_by_dow.items() if v is not None and v > 0}
    if not active:
        return {}
    overall = sum(active.values()) / len(active)
    return {d: (v / overall) for d, v in active.items()}
