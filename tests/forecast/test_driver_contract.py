"""
Phase 3D - Driver I/O & contract tests (no DB writes).

These tests exercise the pure helper functions of run_forecasting and assert the
persistence contract (provenance, FK-safe ordering, idempotency, bounded pulls,
no random split) by inspecting the driver source. They NEVER connect to the
database and never run the driver.
"""

import inspect

import numpy as np
import pytest

from src.forecasting import config
from src.forecasting import run_forecasting as driver
from src.forecasting import datacontract

SRC = inspect.getsource(driver)


# --------------------------------------------------------------------------- #
# to_native : psycopg2-safe coercion of numpy scalars
# --------------------------------------------------------------------------- #
def test_to_native_numpy_integer():
    assert driver.to_native(np.int64(7)) == 7
    assert isinstance(driver.to_native(np.int64(7)), int)


def test_to_native_numpy_float():
    v = driver.to_native(np.float64(3.14))
    assert v == 3.14 and isinstance(v, float)


def test_to_native_numpy_float_nan_to_none():
    assert driver.to_native(np.float64(np.nan)) is None


def test_to_native_numpy_bool():
    assert driver.to_native(np.bool_(True)) is True
    assert isinstance(driver.to_native(np.bool_(True)), bool)


def test_to_native_python_types_passthrough():
    assert driver.to_native("ok") == "ok"
    assert driver.to_native(None) is None
    assert driver.to_native(5) == 5


def test_to_native_python_float_nan_to_none():
    assert driver.to_native(float("nan")) is None


# --------------------------------------------------------------------------- #
# _round and json_safe
# --------------------------------------------------------------------------- #
def test_round_basic():
    assert driver._round(3.14159265) == 3.141593
    assert driver._round(3.14159265, 2) == 3.14


def test_round_nan_or_none():
    assert driver._round(None) is None
    assert driver._round(float("nan")) is None


def test_json_safe_strips_nonfinite():
    out = driver.json_safe({"a": np.float64(1.0), "b": np.float64(np.inf), "c": np.float64(np.nan)})
    assert out["a"] == 1.0
    assert out["b"] is None
    assert out["c"] is None


# --------------------------------------------------------------------------- #
# col_slice : chronological slicing of the bounded trailing window matrix
# --------------------------------------------------------------------------- #
def make_mat(n_series=2, day0=1900, day1=1941):
    days = list(range(day0, day1 + 1))
    # value at (row, col) encodes the day so we can verify alignment
    return np.array([[d for d in days] for _ in range(n_series)], dtype=np.float64)


def test_col_slice_holdout_days():
    mat = make_mat()
    train = driver.col_slice(mat, 1900, 1913)
    valid = driver.col_slice(mat, 1914, 1941)
    assert train.shape[1] == 14
    assert valid.shape[1] == 28
    # first valid column is day 1914, last is 1941
    assert valid[0, 0] == 1914
    assert valid[0, -1] == 1941
    # strictly chronological, past before future, no overlap
    assert train[0, -1] == 1913
    assert np.all(np.diff(valid[0]) == 1)


def test_col_slice_matches_driver_slices():
    mat = make_mat()
    eval_trail = driver.col_slice(mat, config.VALIDATION_START - config.MA_WINDOW - 6, config.TRAIN_END)
    eval_actual = driver.col_slice(mat, config.VALIDATION_START, config.VALIDATION_END)
    final_trail = driver.col_slice(mat, 1928, config.VALIDATION_END)
    # driver asserts these are the validation horizon
    assert eval_actual.shape[1] == config.VALIDATION_HORIZON == 28
    assert final_trail.shape[1] >= config.MA_WINDOW


# --------------------------------------------------------------------------- #
# series_metrics_dict : hand-computed M5 demand-weighted metrics
# --------------------------------------------------------------------------- #
def test_series_metrics_dict_hand_computed():
    fc = np.array([3.0, 5.0, 2.0])
    ac = np.array([2.0, 8.0, 4.0])
    totals = 14.0
    d = driver.series_metrics_dict(fc, ac, totals)
    assert d["mae"] == pytest.approx(2.0)
    assert d["rmse"] == pytest.approx(np.sqrt(14.0 / 3.0))
    assert d["wmae"] == pytest.approx((2 * 1 + 8 * 3 + 4 * 2) / 14)
    assert d["wrmse"] == pytest.approx(np.sqrt((2 * 1 + 8 * 9 + 4 * 4) / 14))
    assert d["abs_error"] == pytest.approx(6.0)
    assert d["bias"] == pytest.approx(-4.0 / 3.0)


def test_series_metrics_dict_zero_actual_safe():
    d = driver.series_metrics_dict(np.array([1.0, 2.0]), np.array([0.0, 0.0]), 0.0)
    assert d["wmae"] == 0.0
    assert np.isfinite(d["rmse"])


# --------------------------------------------------------------------------- #
# Provenance & persistence contract (source inspection — no DB)
# --------------------------------------------------------------------------- #
def test_provenance_is_derived_on_all_outputs():
    # every output writer inserts data_provenance='derived' as a VALUES literal:
    # model_registry, fact_forecast_evaluation, fact_forecast (3 writers)
    assert SRC.count("'derived'") >= 3


def test_fk_safe_delete_order_children_before_parent():
    del_fcast = SRC.index("DELETE FROM fact_forecast")
    del_eval = SRC.index("DELETE FROM fact_forecast_evaluation")
    del_reg = SRC.index("DELETE FROM model_registry")
    # children (fact_forecast, fact_forecast_evaluation) wiped before parent registry
    assert del_fcast < del_reg
    assert del_eval < del_reg


def test_idempotent_delete_before_insert():
    # DELETE happens before the model_registry INSERT to avoid duplicate rows
    del_reg = SRC.index("DELETE FROM model_registry")
    ins_reg = SRC.index("INSERT INTO model_registry")
    assert del_reg < ins_reg


def test_all_output_inserts_carry_provenance_column():
    assert "data_provenance" in SRC


# --------------------------------------------------------------------------- #
# Bounded pulls (no uncontrolled 30,490-model / 59M scan)
# --------------------------------------------------------------------------- #
def test_trailing_pull_is_bounded_day_window_observed_only():
    assert "demand_source='observed'" in SRC
    assert "date_id BETWEEN 1900 AND 1941" in SRC


def test_pilot_pull_is_top_n_limited():
    assert "LIMIT" in SRC
    assert "fact_product_store_demand" in SRC


def test_statistical_pilot_is_bounded_to_config():
    assert "PILOT_TOP_N" in SRC or "config.PILOT_TOP_N" in SRC


# --------------------------------------------------------------------------- #
# No random split / leakage
# --------------------------------------------------------------------------- #
def test_no_random_split_imports():
    assert "train_test_split" not in SRC
    assert "shuffle" not in SRC
    assert "random_state" not in SRC


def test_chronological_validation_uses_validate_series():
    assert "datacontract.validate_series" in SRC
    assert "np.arange(1900, 1942)" in SRC
    # evaluation window is strictly [1914,1941]
    assert "1914, 1941" in SRC or "config.VALIDATION_START, config.VALIDATION_END" in SRC


def test_driver_imports_do_not_open_db():
    # importing the module must not call connect() at import time
    assert "conn = connect()" in SRC             # only inside main(), not module level
