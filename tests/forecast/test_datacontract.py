"""
Phase 3D - Data contract & chronological-split tests.

Covers:
  * chronological (sorted) observed input is accepted
  * unsorted dates are rejected
  * duplicate dates are rejected
  * NaN / Inf units are rejected
  * non-observed provenance is rejected (observed-only forecasting)
  * internal gaps are rejected
  * mismatched lengths are rejected
  * the chronological train/validation split is strictly past -> future
  * shuffled input is rejected
  * a gap between train and validation is rejected
  * insufficient validation data is rejected
  * there is NO random / shuffled split API (no leakage surface)
"""

import numpy as np
import pytest

from src.forecasting import config, datacontract

DAYS = np.arange(1, 1942)          # days 1..1941 (observed window)


def _clean_units() -> np.ndarray:
    units = np.zeros(1941)
    units[-1] = 5.0
    return units


def test_valid_observed_series_accepted():
    # a clean, chronological, observed series must not raise
    datacontract.validate_series(DAYS, _clean_units(), "observed")


def test_unsorted_dates_rejected():
    units = np.ones(1941)
    bad = DAYS.copy()
    bad[10], bad[11] = bad[11], bad[10]      # swap -> out of order
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(bad, units, "observed")


def test_duplicate_dates_rejected():
    units = np.ones(1941)
    bad = DAYS.copy()
    bad[10] = bad[9]                         # duplicate
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(bad, units, "observed")


def test_nan_rejected():
    units = np.ones(1941)
    units[100] = np.nan
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(DAYS, units, "observed")


def test_inf_rejected():
    units = np.ones(1941)
    units[50] = np.inf
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(DAYS, units, "observed")


def test_non_observed_provenance_rejected():
    units = np.ones(1941)
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(DAYS, units, "simulated")
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(DAYS, units, "derived")


def test_internal_gaps_rejected():
    # drop one middle day -> row count no longer covers the [start,end] window
    keep = np.delete(np.arange(1941), 1000)
    days = DAYS[keep]
    units = np.ones(days.size)
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(days, units, "observed")


def test_mismatched_lengths_rejected():
    with pytest.raises(datacontract.DataContractError):
        datacontract.validate_series(DAYS[:1000], np.ones(500), "observed")


def test_chronological_split_strictly_past_to_future():
    units = np.random.RandomState(0).rand(1941)
    train_x, train_y, valid_x, valid_y = datacontract.chronological_split(DAYS, units)
    assert train_x[-1] == config.TRAIN_END
    assert valid_x[0] == config.VALIDATION_START
    assert valid_x[-1] == config.VALIDATION_END
    assert len(valid_x) == config.VALIDATION_HORIZON
    # strictly past -> future, no overlap, monotonic
    assert train_x.max() < valid_x.min()
    assert np.all(np.diff(train_x) > 0)
    assert np.all(np.diff(valid_x) > 0)


def test_shuffled_input_rejected():
    units = np.random.RandomState(1).rand(1941)
    bad = DAYS.copy()
    bad[0], bad[-1] = bad[-1], bad[0]        # breaks chronology
    with pytest.raises(datacontract.DataContractError):
        datacontract.chronological_split(bad, units)


def test_gap_between_train_and_validation_rejected():
    # drop the boundary day so train and validation are not adjacent
    keep = np.delete(np.arange(1941), config.TRAIN_END - 1)   # drop day 1913
    days = DAYS[keep]
    units = np.ones(days.size)
    with pytest.raises(datacontract.DataContractError):
        datacontract.chronological_split(days, units)


def test_insufficient_validation_rejected():
    # only training days present -> validation holdout is empty
    days = np.arange(1, config.TRAIN_END + 1)
    units = np.ones(days.size)
    with pytest.raises(datacontract.DataContractError):
        datacontract.chronological_split(days, units)


def test_no_random_split_api():
    # there is deliberately NO random/shuffled train-test-split surface
    names = [n for n in dir(datacontract) if not n.startswith("_")]
    banned_substrings = ("shuffle", "train_test_split", "random_sample", "random_split")
    for name in names:
        lower = name.lower()
        assert not any(sub in lower for sub in banned_substrings), (
            f"random/shuffled split API leaked: {name}")
    assert "train_test_split" not in names
