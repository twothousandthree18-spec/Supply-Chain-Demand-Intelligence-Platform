"""
Phase 3D - Forecast accuracy metric formula tests (hand-computed reference).

Verifies MAE, RMSE, WMAE, WRMSE, bias and interval computation against known
hand-computed values (L1/L2 norms and demand-weighted errors).
"""

import numpy as np
import pytest

from src.forecasting import metrics


def test_mae_hand_computed():
    fc = np.array([3.0, 5.0, 2.0])
    ac = np.array([2.0, 8.0, 4.0])
    # |1| + |-3| + |-2| = 6 -> mean 2.0
    assert metrics.mae(fc, ac) == pytest.approx(2.0)


def test_rmse_hand_computed():
    fc = np.array([3.0, 5.0, 2.0])
    ac = np.array([2.0, 8.0, 4.0])
    # e = [1, -3, -2], squares = [1, 9, 4], mean = 14/3, sqrt
    assert metrics.rmse(fc, ac) == pytest.approx(np.sqrt(14.0 / 3.0))


def test_wmae_demand_weighted():
    fc = np.array([2.0, 4.0, 6.0])
    ac = np.array([1.0, 3.0, 5.0])
    w = np.array([1.0, 3.0, 5.0])   # demand weights = actuals
    # e = [1,1,1], |e|*w = [1,3,5] -> 9 / (1+3+5)=9 -> 1.0
    assert metrics.wmae(fc, ac, w) == pytest.approx(1.0)


def test_wrmse_demand_weighted():
    fc = np.array([2.0, 4.0, 6.0])
    ac = np.array([1.0, 3.0, 5.0])
    w = np.array([1.0, 3.0, 5.0])
    # e^2*w = [1,3,5] -> 9/9 = 1 -> sqrt = 1
    assert metrics.wrmse(fc, ac, w) == pytest.approx(1.0)


def test_wmae_uniform_weights_equals_mae():
    fc = np.array([1.0, 2.0, 3.0])
    ac = np.array([0.0, 2.0, 4.0])
    # uniform weights  -> same as MAE
    assert metrics.wmae(fc, ac) == pytest.approx(metrics.mae(fc, ac))


def test_bias_sign():
    # over-forecast -> positive bias
    assert metrics.bias([4, 5], [2, 2]) == pytest.approx(2.5)
    # under-forecast -> negative bias
    assert metrics.bias([1, 1], [3, 3]) == pytest.approx(-2.0)


def test_abs_error_is_sum_of_abs():
    fc = np.array([3.0, 5.0])
    ac = np.array([2.0, 8.0])
    # |1| + |-3| = 4
    assert metrics.abs_error(fc, ac) == pytest.approx(4.0)


def test_error_series_and_residual_std():
    fc = np.array([3.0, 5.0, 2.0])
    ac = np.array([2.0, 8.0, 4.0])
    e = metrics.error_series(fc, ac)
    assert np.allclose(e, [1, -3, -2])
    assert metrics.residual_std(e) == pytest.approx(np.std(e, ddof=1))


def test_residual_std_constant_zero_is_none():
    assert metrics.residual_std(np.array([0.0, 0.0, 0.0])) is None


def test_residual_std_single_value():
    assert metrics.residual_std(np.array([2.0])) == pytest.approx(2.0)


def test_forecast_interval():
    lo, hi = metrics.forecast_interval(10.0, 2.0, 1.96)
    assert lo == pytest.approx(10.0 - 1.96 * 2.0)
    assert hi == pytest.approx(10.0 + 1.96 * 2.0)


def test_forecast_interval_no_sigma_returns_point():
    assert metrics.forecast_interval(5.0, None, 1.96) == (5.0, 5.0)


def test_metrics_reject_non_finite():
    with pytest.raises(ValueError):
        metrics.mae([1.0, np.nan], [1.0, 1.0])
    with pytest.raises(ValueError):
        metrics.rmse([1.0, np.inf], [1.0, 1.0])
    with pytest.raises(ValueError):
        metrics.wmae([1.0, 1.0], [1.0, 1.0], [1.0, np.inf])


def test_aggregate_weighted_metrics():
    series = [
        {"wmae": 1.0, "weight": 3.0},
        {"wmae": 3.0, "weight": 1.0},
    ]
    agg = metrics.aggregate_weighted_metrics(series)
    assert agg["wmae"] == pytest.approx((1.0 * 3.0 + 3.0 * 1.0) / 4.0)
