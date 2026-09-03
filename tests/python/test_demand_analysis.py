"""
Supply Chain & Demand Intelligence Platform
Phase 3C - Demand analysis metric tests (pure functions, no DB).

Verifies the mathematical primitives in src/analytics/metrics.py:
trend, seasonality, volatility/CV, growth, segmentation and risk, including
edge cases (zero demand, constant series, zero growth denominators).
"""

import pytest

from src.analytics import metrics, config


# --------------------------------------------------------------------------- #
# Volatility / CV
# --------------------------------------------------------------------------- #
def test_cv_constant_nonezero_is_zero():
    assert metrics.compute_cv([5, 5, 5, 5, 5]) == pytest.approx(0.0)


def test_cv_variable_positive():
    cv = metrics.compute_cv([1, 2, 3, 4, 5])
    # manual: mean=3, std=sqrt(2)~1.414, cv=0.471
    assert cv == pytest.approx(0.4714045, abs=1e-5)


def test_cv_zero_series_none():
    assert metrics.compute_cv([0, 0, 0, 0]) is None


def test_cv_empty_none():
    assert metrics.compute_cv([]) is None


# --------------------------------------------------------------------------- #
# Growth (recent vs prior) with zero-denominator guard
# --------------------------------------------------------------------------- #
def test_growth_normal():
    rate, defined = metrics.compute_growth(recent_mean=120.0, prior_mean=100.0)
    assert defined is True
    assert rate == pytest.approx(0.20)


def test_growth_zero_prior_undefined():
    rate, defined = metrics.compute_growth(recent_mean=50.0, prior_mean=0.0)
    assert defined is False
    assert rate is None


def test_growth_tiny_prior_undefined():
    rate, defined = metrics.compute_growth(recent_mean=50.0, prior_mean=1e-12)
    assert defined is False
    assert rate is None


def test_growth_decline():
    rate, defined = metrics.compute_growth(recent_mean=80.0, prior_mean=100.0)
    assert defined is True
    assert rate == pytest.approx(-0.20)


# --------------------------------------------------------------------------- #
# Trend
# --------------------------------------------------------------------------- #
def test_trend_increasing():
    # positive slope, large span and non-trivial mean -> increasing
    assert metrics.trend_direction(0.5, span=365, mean=50.0) == "increasing"


def test_trend_decreasing():
    assert metrics.trend_direction(-0.5, span=365, mean=50.0) == "decreasing"


def test_trend_flat():
    assert metrics.trend_direction(0.0, span=365, mean=50.0) == "flat"


def test_trend_short_span_flat():
    # too few days -> meaningless trend
    assert metrics.trend_direction(0.5, span=10, mean=50.0) == "flat"


def test_trend_zero_mean_flat():
    assert metrics.trend_direction(0.5, span=365, mean=0.0) == "flat"


def test_trend_effect_pct():
    effect = metrics.trend_effect_pct(0.5, span=365, mean=50.0)
    assert effect == pytest.approx(365.0)  # slope*span/mean*100 = 0.5*365/50*100=365


def test_trend_effect_pct_not_meaningful():
    assert metrics.trend_effect_pct(0.5, span=5, mean=50.0) is None


# --------------------------------------------------------------------------- #
# Seasonality
# --------------------------------------------------------------------------- #
def test_seasonality_clear_annual_pattern():
    means = {i: (100.0 if i == 12 else 50.0) for i in range(1, 13)}
    res = metrics.compute_seasonality(means)
    assert res["meaningful"] is True
    assert res["peak_month"] == 12
    # December index should be above 1.0
    assert res["indices"][12] > 1.0
    assert res["n_active_months"] == 12
    assert res["strength"] is not None and res["strength"] > 0


def test_seasonality_sparse_not_meaningful():
    # only 2 active months -> not enough data, must NOT be flagged meaningful
    res = metrics.compute_seasonality({1: 10.0, 12: 20.0})
    assert res["meaningful"] is False
    assert res["n_active_months"] == 2


def test_seasonality_indices_normalize_around_one():
    means = {i: float(i) for i in range(1, 13)}
    res = metrics.compute_seasonality(means)
    avg_index = sum(res["indices"].values()) / len(res["indices"])
    assert avg_index == pytest.approx(1.0, abs=1e-9)


def test_seasonality_all_flat_not_meaningful_strength_zero():
    res = metrics.compute_seasonality({i: 50.0 for i in range(1, 13)})
    assert res["meaningful"] is False
    assert res["strength"] == pytest.approx(0.0)


def test_seasonality_empty():
    res = metrics.compute_seasonality({})
    assert res["meaningful"] is False
    assert res["indices"] == {}


# --------------------------------------------------------------------------- #
# Segmentation: volume / volatility / demand pattern
# --------------------------------------------------------------------------- #
def test_segment_volume_terciles():
    assert metrics.segment_volume(10.0, low_q=100.0, high_q=200.0) == "Low"
    assert metrics.segment_volume(150.0, low_q=100.0, high_q=200.0) == "Medium"
    assert metrics.segment_volume(250.0, low_q=100.0, high_q=200.0) == "High"


def test_segment_volatility_classes():
    assert metrics.segment_volatility(0.2) == "Low"
    assert metrics.segment_volatility(0.7) == "Medium"
    assert metrics.segment_volatility(1.5) == "High"
    assert metrics.segment_volatility(None) == "High"  # conservative


def test_classify_demand_zero_ratio():
    assert metrics.classify_demand(0.2) == "Smooth"
    assert metrics.classify_demand(0.6) == "Erratic"
    assert metrics.classify_demand(0.85) == "Lumpy"
    assert metrics.classify_demand(0.95) == "Intermittent"
    assert metrics.classify_demand(None) == "Intermittent"


# --------------------------------------------------------------------------- #
# Risk matrix
# --------------------------------------------------------------------------- #
def test_risk_high_high_critical():
    cell, index = metrics.classify_risk("High", "High")
    assert cell == "High*High"
    assert index == 9
    assert metrics.risk_category_from_index(index) == "Critical"


def test_risk_high_medium_high():
    cell, index = metrics.classify_risk("High", "Medium")
    assert index == 6
    assert metrics.risk_category_from_index(index) == "High"


def test_risk_low_low_low():
    _cell, index = metrics.classify_risk("Low", "Low")
    assert index == 1
    assert metrics.risk_category_from_index(index) == "Low"


def test_risk_moderate():
    assert metrics.risk_category_from_index(4) == "High"
    assert metrics.risk_category_from_index(2) == "Moderate"
    assert metrics.risk_category_from_index(3) == "Moderate"


# --------------------------------------------------------------------------- #
# Day-of-week factors
# --------------------------------------------------------------------------- #
def test_dow_factors_weekend_effect():
    # weekends (6,7) demand double the weekdays. Baseline = mean of the 7 day
    # means = (5*50 + 2*100)/7 = 64.2857, so weekend factor = 100/64.2857 = 1.5556.
    means = {d: (100.0 if d >= 6 else 50.0) for d in range(1, 8)}
    factors = metrics.compute_dow_factors(means)
    assert factors[6] == pytest.approx(100.0 / 64.285714, abs=1e-4)
    assert factors[7] == pytest.approx(100.0 / 64.285714, abs=1e-4)
    assert factors[1] == pytest.approx(50.0 / 64.285714, abs=1e-4)


def test_dow_factors_baseline_centered():
    means = {d: 50.0 for d in range(1, 8)}  # flat -> all factors = 1.0
    factors = metrics.compute_dow_factors(means)
    assert all(f == pytest.approx(1.0) for f in factors.values())


def test_dow_factors_empty():
    assert metrics.compute_dow_factors({}) == {}
