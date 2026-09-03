"""
Phase 3E - Safety-stock and reorder-point formula tests (hand-computed).

Verifies the mathematically explicit formulas in src/inventory/formulas.py
against hand-computed cases, including intermittent/zero-demand series safety.

No database is involved.
"""

import math

import numpy as np
import pytest

from src.inventory import config, formulas


# --------------------------------------------------------------------------- #
# z-service quantile
# --------------------------------------------------------------------------- #
def test_z_service_95_matches_config_constant():
    assert formulas.z_service(0.95) == pytest.approx(config.SERVICE_LEVEL_Z, rel=1e-9)


def test_z_service_50_is_zero():
    # z(0.50) must be exactly 0 (median of the standard normal).
    assert formulas.z_service(0.50) == pytest.approx(0.0, abs=1e-4)


def test_z_service_975_is_about_1_96():
    # z(0.975) ~ 1.95996 (this is the value used for a two-sided 95% interval).
    assert formulas.z_service(0.975) == pytest.approx(1.95996398454, rel=1e-3)


def test_z_service_monotonic_increasing():
    lo = formulas.z_service(0.80)
    mid = formulas.z_service(0.95)
    hi = formulas.z_service(0.99)
    assert lo < mid < hi


def test_z_service_out_of_bounds_raises():
    with pytest.raises(ValueError):
        formulas.z_service(0.0)
    with pytest.raises(ValueError):
        formulas.z_service(1.0)
    with pytest.raises(ValueError):
        formulas.z_service(-0.1)


# --------------------------------------------------------------------------- #
# Demand estimators (intermittent / zero safety)
# --------------------------------------------------------------------------- #
def test_expected_daily_demand_mean_hand():
    h = np.array([10.0, 0.0, 20.0, 0.0, 0.0])
    assert formulas.expected_daily_demand(h, "mean") == pytest.approx(6.0)


def test_expected_daily_demand_median_hand():
    h = np.array([10.0, 2.0, 3.0, 1.0, 4.0])
    assert formulas.expected_daily_demand(h, "median") == pytest.approx(3.0)


def test_expected_daily_demand_all_zero_is_zero():
    assert formulas.expected_daily_demand(np.zeros(7)) == pytest.approx(0.0)
    assert formulas.expected_daily_demand(np.array([])) == pytest.approx(0.0)


def test_daily_sigma_hand():
    # variance of [2,4,6] = ((2-4)^2+(4-4)^2+(6-4)^2)/2 = 4 -> std = 2
    h = np.array([2.0, 4.0, 6.0])
    assert formulas.daily_demand_sigma(h, ddof=1) == pytest.approx(2.0)


def test_daily_sigma_constant_series_is_zero():
    # A constant/zero series has no variability -> sigma must be 0 (safe).
    assert formulas.daily_demand_sigma(np.full(10, 5.0)) == pytest.approx(0.0)
    assert formulas.daily_demand_sigma(np.zeros(10)) == pytest.approx(0.0)


def test_mean_absolute_demand_matches_mean():
    h = np.array([3.0, 7.0, 10.0])
    assert formulas.mean_absolute_demand(h) == pytest.approx(20.0 / 3.0)


# --------------------------------------------------------------------------- #
# sigma(lead-time demand) & safety stock
# --------------------------------------------------------------------------- #
def test_sigma_lead_time_demand_hand():
    # daily_sigma=3, lead_time=9 -> 3*sqrt(9)=9
    assert formulas.sigma_lead_time_demand(3.0, 9.0) == pytest.approx(9.0)


def test_sigma_lead_time_demand_zero_lead_time():
    assert formulas.sigma_lead_time_demand(3.0, 0.0) == pytest.approx(0.0)


def test_safety_stock_hand_computed():
    # Hand case: history = [2,4,6] -> daily_sigma=2 (ddof=1).
    # lead_time=9 -> sigma_lt = 2*sqrt(9)=6.
    # service_level=0.95 -> z=1.644853...
    # safety_stock = z*6
    h = np.array([2.0, 4.0, 6.0])
    expected = config.SERVICE_LEVEL_Z * 2.0 * math.sqrt(9.0)
    assert formulas.safety_stock(h, 0.95, 9.0) == pytest.approx(expected, rel=1e-3)


def test_safety_stock_zero_demand_is_zero():
    # All-zero series: sigma=0 -> safety stock 0 (no buffer needed).
    assert formulas.safety_stock(np.zeros(10), 0.95, 7.0) == pytest.approx(0.0)


def test_safety_stock_constant_series_is_zero():
    # Constant positive series has no volatility -> safety stock 0.
    assert formulas.safety_stock(np.full(10, 5.0), 0.95, 7.0) == pytest.approx(0.0)


def test_safety_stock_sigma_override_hand():
    # Explicit sigma_override bypasses history: z(0.95)* (3*sqrt(4)) = z*6
    expected = config.SERVICE_LEVEL_Z * 3.0 * math.sqrt(4.0)
    got = formulas.safety_stock(np.zeros(10), 0.95, 4.0, sigma_override=3.0)
    assert got == pytest.approx(expected, rel=1e-3)


def test_safety_stock_increases_with_service_level():
    h = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    low = formulas.safety_stock(h, 0.90, 7.0)
    high = formulas.safety_stock(h, 0.99, 7.0)
    assert high > low


def test_safety_stock_increases_with_lead_time():
    h = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    short = formulas.safety_stock(h, 0.95, 3.0)
    long_ = formulas.safety_stock(h, 0.95, 10.0)
    assert long_ > short


# --------------------------------------------------------------------------- #
# Expected lead-time demand & reorder point
# --------------------------------------------------------------------------- #
def test_expected_lead_time_demand_hand():
    h = np.array([10.0, 0.0, 20.0, 0.0, 0.0])  # mean = 6
    assert formulas.expected_lead_time_demand(h, 7.0) == pytest.approx(42.0)


def test_reorder_point_hand_computed():
    # history = [2,4,6]: expected_daily=4, lead_time=9 -> lt_demand=36
    # daily_sigma=2 -> sigma_lt=6 -> safety_stock=z(0.95)*6
    # reorder_point = 36 + z*6
    h = np.array([2.0, 4.0, 6.0])
    lt_demand = formulas.expected_lead_time_demand(h, 9.0)
    ss = formulas.safety_stock(h, 0.95, 9.0)
    assert formulas.reorder_point(h, 0.95, 9.0) == pytest.approx(lt_demand + ss)


def test_reorder_point_zero_demand_is_zero():
    # All-zero series -> reorder point 0 (nothing to order or buffer).
    assert formulas.reorder_point(np.zeros(7), 0.95, 7.0) == pytest.approx(0.0)


def test_reorder_point_is_at_least_lead_time_demand():
    h = np.array([3.0, 5.0, 7.0, 9.0])
    lt_demand = formulas.expected_lead_time_demand(h, 7.0)
    assert formulas.reorder_point(h, 0.95, 7.0) >= lt_demand


# --------------------------------------------------------------------------- #
# Reorder quantity
# --------------------------------------------------------------------------- #
def test_reorder_quantity_hand():
    # expected_daily=10, multiple=7 -> Q=70 (no cap)
    assert formulas.reorder_quantity(np.full(5, 10.0), multiple_days=7.0) == pytest.approx(70.0)


def test_reorder_quantity_capped():
    # expected_daily=50, multiple=7 -> 350; max coverage 2 days -> cap 100
    q = formulas.reorder_quantity(np.full(5, 50.0), multiple_days=7.0,
                                  max_coverage_days=2.0)
    assert q == pytest.approx(100.0)


def test_reorder_quantity_zero_demand_is_zero():
    assert formulas.reorder_quantity(np.zeros(5)) == pytest.approx(0.0)


def test_reorder_quantity_explicit_expected_daily():
    assert formulas.reorder_quantity(np.zeros(3), expected_daily=4.0,
                                     multiple_days=7.0) == pytest.approx(28.0)
