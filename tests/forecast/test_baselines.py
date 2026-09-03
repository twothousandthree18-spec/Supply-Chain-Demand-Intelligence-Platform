"""
Phase 3D - Baseline forecast tests (vectorized, hand-computed).

naive, seasonal-naive, moving-average and weighted moving-average forecasts over
a trailing daily-history matrix. All outputs verified against hand computation.
"""

import numpy as np
import pytest

from src.forecasting import config, models


def test_naive_flat_last_value():
    hist = np.array([[3.0, 7.0, 2.0],
                     [1.0, 1.0, 5.0]])
    fc = models.naive(hist, 4)
    assert fc.shape == (2, 4)
    assert np.allclose(fc[0], 2.0)
    assert np.allclose(fc[1], 5.0)


def test_naive_horizon_and_vectorized():
    hist = np.array([[1.0, 2.0, 3.0]])
    fc = models.naive(hist, 28)
    assert fc.shape == (1, 28)
    assert np.allclose(fc, 3.0)


def test_seasonal_naive_cycles_last_week():
    # last period = [10,20,30,40,50,60,70] -> repeats cyclically
    hist = np.array([[0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]])
    fc = models.seasonal_naive(hist, 10)
    expected = [10, 20, 30, 40, 50, 60, 70, 10, 20, 30]
    assert np.allclose(fc[0], expected)


def test_seasonal_naive_exact_one_period():
    hist = np.array([[5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]])
    fc = models.seasonal_naive(hist, 7)
    assert np.allclose(fc[0], [5, 6, 7, 8, 9, 10, 11])


def test_seasonal_naive_history_too_short_raises():
    with pytest.raises(ValueError):
        models.seasonal_naive(np.array([[1.0, 2.0, 3.0]]), 5)


def test_moving_average_flat_mean_last_window():
    hist = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]])
    # last 7 mean = 4.0
    fc = models.moving_average(hist, 5)
    assert np.allclose(fc[0], 4.0)


def test_moving_average_window_longer_than_history():
    hist = np.array([[2.0, 4.0, 6.0]])      # window clamps to 3 -> mean 4
    fc = models.moving_average(hist, 3)
    assert np.allclose(fc[0], 4.0)


def test_weighted_ma_hand_computed():
    # window 3, weights [1,2,3] over last 3 = [1,2,3] -> (1*1+2*2+3*3)/(1+2+3)
    hist = np.array([[0.0, 1.0, 2.0, 3.0]])
    fc = models.weighted_ma(hist, 2, window=3)
    expected = (1 * 1 + 2 * 2 + 3 * 3) / 6   # 14/6
    assert np.allclose(fc[0], expected)


def test_weighted_ma_prioritises_recent():
    # more weight on the newest value; recent=100 pulls forecast up
    hist = np.array([[1.0, 1.0, 1.0, 100.0]])
    fc = models.weighted_ma(hist, 1, window=4)
    # weights [1,2,3,4] over [1,1,1,100] -> (1+2+3+400)/10 = 40.6
    assert fc[0, 0] == pytest.approx(40.6)


def test_weighted_ma_equals_ma_when_flat():
    hist = np.array([[5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]])
    assert np.allclose(models.weighted_ma(hist, 4), 5.0)


def test_baselines_all_present_and_deterministic():
    assert set(models.BASELINES) == {"naive", "seasonal_naive", "moving_average", "weighted_ma"}
    hist = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]])
    out1 = {k: models.BASELINES[k](hist, 28) for k in models.BASELINES}
    out2 = {k: models.BASELINES[k](hist, 28) for k in models.BASELINES}
    for k in models.BASELINES:
        assert np.array_equal(out1[k], out2[k])          # reproducible
        assert out1[k].shape[1] == config.FINAL_HORIZON  # 28-day horizon


def test_baselines_zero_and_single_value_histories():
    zero = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]])
    assert np.allclose(models.naive(zero, 5), 0.0)
    assert np.allclose(models.moving_average(zero, 5), 0.0)
    assert np.allclose(models.weighted_ma(zero, 5), 0.0)
    single = np.array([[3.0]])
    assert np.allclose(models.naive(single, 5), 3.0)
    assert np.allclose(models.moving_average(single, 5), 3.0)   # clamps to window 1
    assert np.allclose(models.weighted_ma(single, 5), 3.0)      # clamps to window 1
