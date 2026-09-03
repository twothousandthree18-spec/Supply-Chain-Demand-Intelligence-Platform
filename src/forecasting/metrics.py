"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Forecast accuracy metrics (pure, DB-free).

Every function here is a deterministic transformation over plain Python/numpy
inputs so it can be unit-tested without a database.

Formulas follow standard demand-forecasting conventions (M5 uses demand-weighted
errors). For a vector of forecasts f, actuals a and weights w (= observed demand,
falling back to uniform when no weights are supplied):

    error        e_i  = f_i - a_i
    MAE          = mean(|e_i|)
    RMSE         = sqrt( mean(e_i^2) )
    WMAE         = sum(w_i * |e_i|) / sum(w_i)
    WRMSE        = sqrt( sum(w_i * e_i^2) / sum(w_i) )
    bias         = mean(e_i)             (positive = over-forecast)

NaN/Inf in inputs are rejected by the caller's data-contract checks; the
functions assume finite inputs (see data_contract.validate).
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def _as_np(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


def _finite_or_raise(values: np.ndarray, name: str) -> None:
    if not np.all(np.isfinite(values)):
        raise ValueError(f"non-finite value in {name}")


def mae(forecast, actual) -> float:
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    return float(np.mean(np.abs(f - a)))


def rmse(forecast, actual) -> float:
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    return float(np.sqrt(np.mean((f - a) ** 2)))


def wmae(forecast, actual, weights=None) -> float:
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    w = _as_np(weights) if weights is not None else np.ones_like(f)
    if w.size != f.size:
        raise ValueError("weights length must match forecast/actual length")
    _finite_or_raise(w, "weights")
    wsum = float(np.sum(w))
    if wsum <= 0:
        raise ValueError("weights sum must be positive")
    return float(np.sum(w * np.abs(f - a)) / wsum)


def wrmse(forecast, actual, weights=None) -> float:
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    w = _as_np(weights) if weights is not None else np.ones_like(f)
    if w.size != f.size:
        raise ValueError("weights length must match forecast/actual length")
    _finite_or_raise(w, "weights")
    wsum = float(np.sum(w))
    if wsum <= 0:
        raise ValueError("weights sum must be positive")
    return float(np.sqrt(np.sum(w * (f - a) ** 2) / wsum))


def bias(forecast, actual) -> float:
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    return float(np.mean(f - a))


def abs_error(forecast, actual) -> float:
    return mae(forecast, actual) * _as_np(actual).size


def error_series(forecast, actual) -> np.ndarray:
    """Signed per-step errors e = f - a (used for residual std / intervals)."""
    f = _as_np(forecast)
    a = _as_np(actual)
    _finite_or_raise(f, "forecast")
    _finite_or_raise(a, "actual")
    return f - a


def residual_std(error: np.ndarray) -> Optional[float]:
    """Sample standard deviation of an error vector (None when there is no
    measurable spread, i.e. empty or a constant error series)."""
    e = _as_np(error)
    if e.size == 0:
        return None
    _finite_or_raise(e, "error")
    if e.size == 1:
        return float(abs(e[0])) if abs(e[0]) > 0 else None
    s = float(np.std(e, ddof=1))
    if not (np.isfinite(s) and s > 0):
        # a constant error series has zero dispersion -> no measurable spread
        return None
    return s


def forecast_interval(point: float, sigma: Optional[float], z: float):
    """Return (lower, upper) for a point forecast given residual std sigma.

    When sigma is None (no measurable uncertainty) return (point, point).
    Lower bound is not floored here; the driver clamps negatives to config.MIN_PI_ABS.
    """
    if sigma is None or sigma <= 0:
        return (point, point)
    half = z * sigma
    return (point - half, point + half)


def aggregate_weighted_metrics(per_series_metrics: list) -> dict:
    """Weighted (by series total demand) summary of per-series metric dicts.

    per_series_metrics: list of {"wmae": .., "wrmse": .., "mae": .., "rmse": ..,
    "bias": .., "weight": ..}. Returns a dict of demand-weighted averages over
    the series' WMAE/WRMSE/MAE/RMSE/bias.
    """
    n = len(per_series_metrics)
    if n == 0:
        return {}
    for key in ("wmae", "wrmse", "mae", "rmse", "bias"):
        if all(m.get(key) is not None for m in per_series_metrics) and sum(
            m.get("weight", 0.0) for m in per_series_metrics
        ) > 0:
            total_w = sum(m.get("weight", 0.0) for m in per_series_metrics)
            return {key: sum(m.get(key, 0.0) * m.get("weight", 0.0) for m in per_series_metrics) / total_w
                    for key in ("wmae", "wrmse", "mae", "rmse", "bias")}
    return {}
