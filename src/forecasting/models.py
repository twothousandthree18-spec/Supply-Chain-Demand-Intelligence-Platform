"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Forecast models (deterministic, bounded).

Baselines (naive, seasonal-naive, moving / weighted moving average) operate on a
compact trailing window of daily units and are cheap enough to run on ALL
product/store series using vectorized numpy.

Statistical models (ETS / Holt-Winters, SARIMA) are fitted ONLY on the bounded
pilot subset (see config.PILOT_TOP_N) because fitting every one of the 30,490
series would be an uncontrolled computation. They wrap statsmodels with fixed,
documented orders and a hard fall-back to a simple exponential-smoothing /
naive forecast when the numerical fit fails (common on very sparse daily M5
series). Nothing here ever shuffles or uses future data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import config

# --------------------------------------------------------------------------- #
# Baselines (vectorized over series via a trailing-window matrix)
# --------------------------------------------------------------------------- #
def naive(hist: np.ndarray, horizon: int) -> np.ndarray:
    """Flat forecast equal to the last observed value."""
    hist = np.asarray(hist, dtype=np.float64)
    last = hist[..., -1:]
    return np.repeat(last, horizon, axis=-1)


def seasonal_naive(hist: np.ndarray, horizon: int, period: int = config.SEASONALITY) -> np.ndarray:
    """Repeat the last `period` observed values cyclically (weekly seasonality)."""
    hist = np.asarray(hist, dtype=np.float64)
    if hist.shape[-1] < period:
        raise ValueError("history shorter than seasonal period")
    pattern = hist[..., -period:]
    reps = int(np.ceil(horizon / period))
    return np.tile(pattern, reps)[..., :horizon]


def moving_average(hist: np.ndarray, horizon: int, window: int = config.MA_WINDOW) -> np.ndarray:
    """Flat forecast equal to the mean of the last `window` observed values."""
    hist = np.asarray(hist, dtype=np.float64)
    if hist.shape[-1] < window:
        window = hist.shape[-1]
    mean = np.mean(hist[..., -window:], axis=-1, keepdims=True)
    return np.repeat(mean, horizon, axis=-1)


def weighted_ma(hist: np.ndarray, horizon: int, window: int = config.MA_WINDOW) -> np.ndarray:
    """Flat forecast equal to a linearly-weighted mean of the last `window` values,
    weighting recent points most heavily (weights 1..window, newest = window)."""
    hist = np.asarray(hist, dtype=np.float64)
    if hist.shape[-1] < window:
        window = hist.shape[-1]
    w = np.arange(1, window + 1, dtype=np.float64)          # oldest..newest
    last_w = hist[..., -window:]
    weighted = np.sum(last_w * w, axis=-1, keepdims=True) / np.sum(w)
    return np.repeat(weighted, horizon, axis=-1)


BASELINES = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "moving_average": moving_average,
    "weighted_ma": weighted_ma,
}


# --------------------------------------------------------------------------- #
# Statistical models (bounded pilot subset, deterministic with hard fallback)
# --------------------------------------------------------------------------- #
@dataclass
class FitResult:
    point: np.ndarray            # (horizon,) point forecast
    ok: bool = True
    family: str = "statistical"
    note: Optional[str] = None
    obj: Optional[object] = None  # optional fitted statsmodels object (unused downstream)

    @property
    def horizon(self) -> int:
        return int(self.point.size)


def _to_series(y) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64).ravel()
    if y.size < config.MIN_TRAIN_POINTS:
        raise ValueError("too few training points")
    return y


def _check_positive_finite(y: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(y))) and bool(np.any(y > 0))


def fit_ets_holt_winters(y, horizon: int = config.FINAL_HORIZON) -> FitResult:
    """Holt-Winters additive exponential smoothing (ETS).

    On sparse/all-zero series (common in M5 daily data) the optimizer can fail;
    we fall back to simple exponential smoothing and then to naive, and set
    ok=False with a note so the pilot comparison documents it.
    """
    try:
        yv = _to_series(y)
        if not _check_positive_finite(yv):
            return FitResult(naive(yv, horizon), ok=False, note="non-positive/finite series")
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        model = ExponentialSmoothing(
            yv, trend="add", seasonal="add", seasonal_periods=config.SEASONALITY,
            initialization_method="estimated", damped_trend=False,
        )
        fit = model.fit(optimized=True)
        fc = np.asarray(fit.forecast(horizon), dtype=np.float64)
        if not np.all(np.isfinite(fc)):
            raise ValueError("non-finite ETS forecast")
        fc = np.clip(fc, 0.0, None)
        return FitResult(fc, ok=True, obj=fit)
    except Exception as exc:  # noqa: BLE001
        try:
            yv = _to_series(y)
            # fall back to simple exponential smoothing (Holt's level only)
            from statsmodels.tsa.holtwinters import SimpleExpSmoothing

            sfit = SimpleExpSmoothing(yv).fit(optimized=True)
            fc = np.clip(np.asarray(sfit.forecast(horizon), dtype=np.float64), 0.0, None)
            if np.all(np.isfinite(fc)):
                return FitResult(fc, ok=False, note=f"ETS fell back to SES: {exc}")
        except Exception:  # noqa: BLE001
            pass
        yv = _to_series(y)
        return FitResult(naive(yv, horizon), ok=False, note=f"ETS failed: {exc}")


def fit_sarima(y, horizon: int = config.FINAL_HORIZON) -> FitResult:
    """SARIMA(0,1,1)x(0,1,1,7) — a fixed, bounded, single statistical variant.

    Fitted only on the pilot subset. High-zero weekly demand often makes the
    seasonal differencing numerically unstable; on failure we fall back to the
    seasonal-naive baseline and mark ok=False so the pilot comparison documents it.
    """
    try:
        yv = _to_series(y)
        if not _check_positive_finite(yv):
            return FitResult(seasonal_naive(yv, horizon), ok=False, note="non-positive/finite series")
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        from statsmodels.tsa.statespace.tools import diff

        model = SARIMAX(
            yv,
            order=(0, 1, 1),
            seasonal_order=(0, 1, 1, config.SEASONALITY),
            enforce_stationarity=False,
            enforce_invertibility=False,
            trend="c",
        )
        fit = model.fit(disp=False, maxiter=200)
        fc = np.asarray(fit.forecast(horizon), dtype=np.float64)
        if not np.all(np.isfinite(fc)):
            raise ValueError("non-finite SARIMA forecast")
        fc = np.clip(fc, 0.0, None)
        return FitResult(fc, ok=True, obj=fit)
    except Exception as exc:  # noqa: BLE001
        yv = _to_series(y)
        return FitResult(seasonal_naive(yv, horizon), ok=False, note=f"SARIMA failed: {exc}")


STATISTICAL = {
    "ets_holt_winters": fit_ets_holt_winters,
    "sarima": fit_sarima,
}
