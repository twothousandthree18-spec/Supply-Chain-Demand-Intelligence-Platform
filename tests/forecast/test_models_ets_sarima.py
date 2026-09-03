"""
Phase 3D - Bounded statistical model tests (ETS/Holt-Winters, SARIMA).

These tests run on SMALL deterministic series ONLY. They do NOT fit any model
across the 30,490 series and do NOT glance at the database.

Contract under test:
  * fixed pre-trained-by-driver read is out of scope; here we exercise the
    fit functions directly on tiny series.
  * outputs are finite point forecasts of exactly `horizon` length (28).
  * sparse / all-zero series fall back to a baseline with ok=False (never a
    numerical blow-up) and stay finite.
  * too-few training points are rejected (never silently fit).
  * fitters are deterministic (same input -> same output).
"""

import numpy as np
import pytest

from src.forecasting import config, models


def _seasonal_series(n=112, period=7, trend=0.05, seed=0):
    """A gentle weekly seasonal series with a small trend + noise."""
    rng = np.random.RandomState(seed)
    days = np.arange(n)
    base = 10.0 + trend * days + 3.0 * np.sin(2 * np.pi * days / period)
    noise = rng.normal(0, 0.5, n)
    return np.maximum(0.0, base + noise)


# --------------------------------------------------------------------------- #
# ETS / Holt-Winters
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("horizon", [1, 7, 28])
def test_ets_finite_output_and_horizon(horizon):
    y = _seasonal_series()
    res = models.fit_ets_holt_winters(y, horizon)
    assert isinstance(res.point, np.ndarray)
    assert res.point.shape == (horizon,)
    assert np.all(np.isfinite(res.point))
    assert np.all(res.point >= 0)                 # clipped at zero


def test_ets_deterministic():
    y = _seasonal_series()
    a = models.fit_ets_holt_winters(y, 28).point
    b = models.fit_ets_holt_winters(y, 28).point
    assert np.allclose(a, b)


def test_ets_zero_series_falls_back_naive():
    y = np.zeros(60)
    res = models.fit_ets_holt_winters(y, 28)
    assert res.ok is False
    assert res.point.shape == (28,)
    assert np.all(np.isfinite(res.point))
    assert np.allclose(res.point, 0.0)            # baseline naive on zero series


def test_ets_short_series_rejected():
    with pytest.raises(ValueError):
        models.fit_ets_holt_winters(np.ones(10), 28)


# --------------------------------------------------------------------------- #
# SARIMA
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("horizon", [1, 7, 28])
def test_sarima_finite_output_and_horizon(horizon):
    y = _seasonal_series(n=84)
    res = models.fit_sarima(y, horizon)
    assert isinstance(res.point, np.ndarray)
    assert res.point.shape == (horizon,)
    assert np.all(np.isfinite(res.point))
    assert np.all(res.point >= 0)


def test_sarima_deterministic():
    y = _seasonal_series(n=84)
    a = models.fit_sarima(y, 28).point
    b = models.fit_sarima(y, 28).point
    assert np.allclose(a, b)


def test_sarima_zero_series_falls_back_seasonal_naive():
    y = np.zeros(84)
    res = models.fit_sarima(y, 28)
    assert res.ok is False
    assert res.point.shape == (28,)
    assert np.all(np.isfinite(res.point))
    assert np.allclose(res.point, 0.0)            # seasonal-naive on zero series


def test_sarima_short_series_rejected():
    with pytest.raises(ValueError):
        models.fit_sarima(np.ones(10), 28)


# --------------------------------------------------------------------------- #
# Model registry maps (bounded stat family)
# --------------------------------------------------------------------------- #
def test_statistical_map_contains_only_bounded_models():
    assert set(models.STATISTICAL) == {"ets_holt_winters", "sarima"}


def test_fit_result_horizon_property():
    r = models.FitResult(np.zeros(28))
    assert r.horizon == 28
    assert r.ok is True
    assert r.family == "statistical"


def test_no_large_arima_workload_in_tests():
    # Guard: these tests must never launch a big batch. The fitters only accept
    # a 1-D series, so they structurally cannot iterate over 30,490 series.
    import inspect
    for fn in (models.fit_ets_holt_winters, models.fit_sarima):
        sig = inspect.signature(fn)
        assert list(sig.parameters) == ["y", "horizon"], (
            "fitter signature changed; only single-series usage allowed")
