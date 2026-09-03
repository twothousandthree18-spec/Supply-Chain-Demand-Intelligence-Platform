"""
Phase 3E - Inventory position logic tests (hand-computed).

Covers the rolling per-day state machine (advance_day), the reorder trigger,
starting inventory, stockout/backorder handling, and inventory-position math.

No database is involved.
"""

import numpy as np
import pytest

from src.inventory import formulas


# --------------------------------------------------------------------------- #
# Reorder trigger
# --------------------------------------------------------------------------- #
def test_trigger_false_above_reorder_point():
    assert formulas.reorder_trigger(11.0, 10.0) is False


def test_trigger_true_at_reorder_point():
    # Boundary: position == reorder point must trigger (<=).
    assert formulas.reorder_trigger(10.0, 10.0) is True


def test_trigger_true_below_reorder_point():
    assert formulas.reorder_trigger(9.0, 10.0) is True


# --------------------------------------------------------------------------- #
# start-of-horizon inventory
# --------------------------------------------------------------------------- #
def test_starting_inventory_coverage_hand():
    # history mean = 10, coverage 7 days -> starting on-hand = 70
    h = np.array([10.0, 10.0, 10.0])
    assert formulas.starting_inventory_coverage(h, 7.0) == pytest.approx(70.0)


def test_starting_inventory_coverage_zero_series():
    assert formulas.starting_inventory_coverage(np.zeros(7), 7.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# advance_day: no stockout, no reorder
# --------------------------------------------------------------------------- #
def test_advance_no_stockout_no_reorder():
    # start on_hand=10, on_order=0, backorder=0, demand=4, ROP=5, Q=10
    # total=4, fulfilled=4, on_hand=6, backorder=0, position=6 > ROP -> no order
    s = formulas.advance_day(on_hand=10, on_order=0, backorder=0, demand=4,
                             reorder_point_value=5, order_qty=10)
    assert s.on_hand == pytest.approx(6.0)
    assert s.backorder == pytest.approx(0.0)
    assert s.inventory_position == pytest.approx(6.0)
    assert s.stockout is False
    assert s.stockout_units == pytest.approx(0.0)
    assert s.orders_placed == 0.0
    assert s.order_qty == 0.0


# --------------------------------------------------------------------------- #
# advance_day: stockout -> backorder carried, reorder placed
# --------------------------------------------------------------------------- #
def test_advance_stockout_backorder_and_reorder():
    # on_hand=3, on_order=0, backorder=2, demand=5
    # total=7, fulfilled=3, unmet=4 -> on_hand=0, backorder=4, position=-4
    # position -4 <= ROP 10 -> order Q=8: on_order=8, position=4
    s = formulas.advance_day(on_hand=3, on_order=0, backorder=2, demand=5,
                             reorder_point_value=10, order_qty=8)
    assert s.on_hand == pytest.approx(0.0)
    assert s.backorder == pytest.approx(4.0)          # unmet carried forward
    assert s.inventory_position == pytest.approx(4.0)  # 0 + 8 - 4
    assert s.on_order == pytest.approx(8.0)
    assert s.stockout is True
    assert s.stockout_units == pytest.approx(4.0)
    assert s.order_qty == pytest.approx(8.0)
    assert s.orders_placed == 1.0


# --------------------------------------------------------------------------- #
# advance_day: reorder at the boundary (position == ROP)
# --------------------------------------------------------------------------- #
def test_advance_reorder_when_position_equals_reorder_point():
    # on_hand=5, demand=0 -> position=5 == ROP 5 -> order
    s = formulas.advance_day(on_hand=5, on_order=0, backorder=0, demand=0,
                             reorder_point_value=5, order_qty=10)
    assert s.on_hand == pytest.approx(5.0)
    assert s.inventory_position == pytest.approx(15.0)  # 5 + 10
    assert s.order_qty == pytest.approx(10.0)
    assert s.orders_placed == 1.0


# --------------------------------------------------------------------------- #
# advance_day: on_order raises position above ROP -> no trigger
# --------------------------------------------------------------------------- #
def test_advance_on_order_contributes_to_position_no_trigger():
    # on_hand=2, on_order=9, demand=0 -> position=11 > ROP 10 -> no order
    s = formulas.advance_day(on_hand=2, on_order=9, backorder=0, demand=0,
                             reorder_point_value=10, order_qty=12)
    assert s.on_hand == pytest.approx(2.0)
    assert s.inventory_position == pytest.approx(11.0)
    assert s.orders_placed == 0.0
    assert s.on_order == pytest.approx(9.0)


# --------------------------------------------------------------------------- #
# advance_day: full stockout when on_hand=0
# --------------------------------------------------------------------------- #
def test_advance_zero_on_hand_full_stockout():
    # on_hand=0, demand=6, backorder=0 -> all demand unfulfilled
    s = formulas.advance_day(on_hand=0, on_order=0, backorder=0, demand=6,
                             reorder_point_value=0, order_qty=0)
    assert s.on_hand == pytest.approx(0.0)
    assert s.backorder == pytest.approx(6.0)
    assert s.stockout is True
    assert s.stockout_units == pytest.approx(6.0)
    # Q=0 so no order is placed even at the ROP
    assert s.orders_placed == 0.0


# --------------------------------------------------------------------------- #
# advance_day: does not over-serve; negative-position math is exact
# --------------------------------------------------------------------------- #
def test_advance_position_can_be_negative_when_backordered():
    # on_hand=0, on_order=0, backorder=3, demand=0 -> position=-3
    s = formulas.advance_day(on_hand=0, on_order=0, backorder=3, demand=0,
                             reorder_point_value=0, order_qty=0)
    assert s.backorder == pytest.approx(3.0)              # carried
    assert s.inventory_position == pytest.approx(-3.0)    # 0 + 0 - 3


# --------------------------------------------------------------------------- #
# Excess inventory
# --------------------------------------------------------------------------- #
def test_excess_inventory_hand():
    # on_hand=100, expected_daily=10, ceiling=28 days -> excess=100-280<0 -> 0
    assert formulas.excess_inventory(100.0, 10.0, 28.0) == pytest.approx(0.0)


def test_excess_inventory_positive():
    # on_hand=300, expected_daily=10, ceiling=28 days=280 -> excess=20
    assert formulas.excess_inventory(300.0, 10.0, 28.0) == pytest.approx(20.0)


def test_excess_inventory_zero_expected_demand():
    assert formulas.excess_inventory(300.0, 0.0, 28.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Days of inventory
# --------------------------------------------------------------------------- #
def test_days_of_inventory_hand():
    # on_hand=140, expected_daily=7 -> 20 days
    assert formulas.days_of_inventory(140.0, 7.0) == pytest.approx(20.0)


def test_days_of_inventory_zero_expected_demand():
    # No expected demand -> cannot compute days on hand -> 0 (safe)
    assert formulas.days_of_inventory(100.0, 0.0) == pytest.approx(0.0)


def test_days_of_inventory_zero_on_hand():
    assert formulas.days_of_inventory(0.0, 7.0) == pytest.approx(0.0)
