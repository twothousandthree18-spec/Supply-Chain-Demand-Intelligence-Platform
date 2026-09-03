"""
Phase 3E - Inventory simulation engine tests (hand-computed transitions).

Covers the full-day state transitions of src/inventory/simulation.py:
starting inventory, arrivals with a fixed lead time, on-order decrementing,
(s,Q) reorder trigger, backorder carry, stockouts, replenishment recovery,
out-of-horizon in-flight orders, determinism, validation, provenance
separation, and the fact_inventory_simulation column contract.

No database is involved.
"""

import numpy as np
import pytest

from src.inventory import config, formulas
from src.inventory.simulation import (
    DailySimulationRecord,
    InventoryPolicy,
    compute_policy,
    record_field_names,
    simulate_series,
)


def _policy(**overrides):
    """Minimal explicit policy for hand-computed cases."""
    base = dict(
        expected_daily_demand=1.0,
        safety_stock=0.0,
        reorder_point=5.0,
        reorder_quantity=50.0,
        starting_inventory=3.0,
        lead_time_demand=7.0,
        lead_time_days=7.0,
        excess_coverage_days=28.0,
        service_level=0.95,
    )
    base.update(overrides)
    return InventoryPolicy(**base)


# --------------------------------------------------------------------------- #
# Starting-inventory convention: end-of-day on_hand carries to next day start
# (pre-arrival), including across replenishment-arrival days
# --------------------------------------------------------------------------- #
def test_start_of_day_carries_previous_end_of_day_on_hand():
    # lead=1 => day2 has a 50-unit arrival; day2.starting_inventory must still
    # equal day1.on_hand (pre-arrival physical stock).
    p = _policy(starting_inventory=10.0, reorder_point=5.0,
                reorder_quantity=50.0, lead_time_days=1.0)
    r = simulate_series([6.0, 2.0, 3.0, 1.0], policy=p, start_day=1942)
    for prev, nxt in zip(r.days, r.days[1:]):
        assert nxt.starting_inventory == pytest.approx(prev.on_hand)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_simulation_is_deterministic():
    fc = [5.0] * 28
    a = simulate_series(fc, policy=_policy())
    b = simulate_series(np.array(fc), policy=_policy())
    assert a.days == b.days
    assert a.final_backorder == b.final_backorder
    assert a.final_on_order == b.final_on_order
    assert a.service_level == b.service_level


# --------------------------------------------------------------------------- #
# Hand-computed: replenishment arrival with lead time 1 (on-order decrement)
# --------------------------------------------------------------------------- #
def test_arrival_replenishes_on_order_decrements_and_no_double_order():
    # policy: starting=10, rop=5, qty=50, lead=1; demand=[6,2]
    p = _policy(starting_inventory=10.0, reorder_point=5.0,
                reorder_quantity=50.0, lead_time_days=1.0)
    r = simulate_series([6.0, 2.0], policy=p, start_day=1942)

    d1, d2 = r.days
    # day 1942: S=10, demand 6 -> on_hand 4, pos 4<=5 -> order 50 -> pos 54
    assert d1.day_id == 1942
    assert d1.starting_inventory == pytest.approx(10.0)
    assert d1.on_hand == pytest.approx(4.0)
    assert d1.inventory_position == pytest.approx(54.0)
    assert d1.orders_placed == pytest.approx(1.0)
    assert d1.reorder_qty == pytest.approx(50.0)
    assert d1.projected_stockout is False
    assert d1.stockout_units == pytest.approx(0.0)

    # day 1943: arrival of 50 -> on_hand 54, on_order 0; demand 2 -> on_hand 52
    assert d2.day_id == 1943
    assert d2.starting_inventory == pytest.approx(4.0)
    assert d2.on_hand == pytest.approx(52.0)
    assert d2.inventory_position == pytest.approx(52.0)
    assert d2.orders_placed == pytest.approx(0.0)
    assert r.final_on_order == pytest.approx(0.0)
    assert r.final_backorder == pytest.approx(0.0)
    assert r.total_orders_placed == 1


# --------------------------------------------------------------------------- #
# Hand-computed: stockout -> backorder carry -> replenishment recovery
# (28-day horizon, lead time 7, demand 5/day)
# --------------------------------------------------------------------------- #
def test_stockout_backorder_and_replenishment_cycle():
    p = _policy()  # starting=3, rop=5, qty=50, lead=7
    r = simulate_series([5.0] * 28, policy=p, start_day=1942)

    assert len(r.days) == 28
    first, second = r.days[0], r.days[1]

    # day 1942: S=3, demand 5 -> 3 served, 2 short; pos -2 <= 5 -> order 50
    assert first.day_id == 1942
    assert first.starting_inventory == pytest.approx(3.0)
    assert first.on_hand == pytest.approx(0.0)
    assert first.projected_stockout is True
    assert first.stockout_units == pytest.approx(2.0)
    assert first.inventory_position == pytest.approx(48.0)   # -2 + 50
    assert first.reorder_qty == pytest.approx(50.0)

    # day 1943: no arrival yet; carried backorder 2 + demand 5 = 7 unmet
    assert second.day_id == 1943
    assert second.starting_inventory == pytest.approx(0.0)
    assert second.stockout_units == pytest.approx(7.0)
    assert second.inventory_position == pytest.approx(43.0)  # 0 + 50 - 7
    assert second.orders_placed == pytest.approx(0.0)

    # day 1949: order from 1942 (arrival 1942+7) lands -> backlog cleared
    arrival = r.days[7]
    assert arrival.day_id == 1949
    assert arrival.on_hand == pytest.approx(13.0)     # 50 - 37 total
    assert arrival.projected_stockout is False
    assert arrival.stockout_units == pytest.approx(0.0)
    assert arrival.inventory_position == pytest.approx(13.0)

    # day 1951: position drops to 3 <= 5 again -> second order (arr. 1958)
    reorder_day = r.days[9]
    assert reorder_day.day_id == 1951
    assert reorder_day.on_hand == pytest.approx(3.0)
    assert reorder_day.reorder_qty == pytest.approx(50.0)

    # summary
    assert r.total_orders_placed == 3
    assert pytest.approx(r.total_reorder_units) == 150.0
    assert pytest.approx(r.final_on_hand) == 13.0
    assert r.final_backorder == pytest.approx(0.0)
    assert r.final_on_order == pytest.approx(0.0)
    # stockout days: 1942, 1943-48 (7), 1952-57 (6), 1962-67 (6) = 19
    assert r.stockout_days == 19
    assert r.service_level == pytest.approx(1.0 - 19 / 28)
    assert r.fill_rate == pytest.approx(1.0)  # all demand served by horizon end


# --------------------------------------------------------------------------- #
# Hand-computed: orders placed near horizon stay in-flight (no phantom arrivals)
# --------------------------------------------------------------------------- #
def test_out_of_horizon_orders_remain_in_flight():
    # policy: starting=1, rop=1000 (always trigger), qty=10, lead=7;
    # 5 zero-demand days -> one order/day, arrivals all beyond day 5.
    p = _policy(starting_inventory=1.0, reorder_point=1000.0,
                reorder_quantity=10.0, lead_time_days=7.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)

    assert len(r.days) == 5
    assert r.days[-1].day_id == 1946
    assert r.total_orders_placed == 5
    assert r.total_reorder_units == pytest.approx(50.0)
    assert r.final_on_order == pytest.approx(50.0)   # 5 x 10, no arrivals
    assert r.final_in_flight == pytest.approx(50.0)
    assert r.final_on_hand == pytest.approx(1.0)
    assert r.final_backorder == pytest.approx(0.0)
    assert r.stockout_days == 0


# --------------------------------------------------------------------------- #
# No-stockout, no-reorder trace (order_qty=0 disables ordering)
# --------------------------------------------------------------------------- #
def test_no_reorder_and_no_stockout_with_zero_order_quantity():
    # starting=10, rop=5, qty=0 -> never order; demand never exceeds stock
    p = _policy(starting_inventory=10.0, reorder_point=5.0,
                reorder_quantity=0.0, lead_time_days=7.0)
    r = simulate_series([1.0, 2.0, 3.0, 4.0], policy=p, start_day=1942)

    on_hands = [rec.on_hand for rec in r.days]
    assert on_hands == pytest.approx([9.0, 7.0, 4.0, 0.0])
    assert all(rec.orders_placed == pytest.approx(0.0) for rec in r.days)
    assert not any(rec.projected_stockout for rec in r.days)
    assert r.final_on_order == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Default-config path: policy derived from history, 28-day [1942,1969] horizon
# --------------------------------------------------------------------------- #
def test_default_config_path_horizon_and_policy():
    history = np.full(28, 10.0)          # constant -> sigma=0 -> safety stock 0
    fc = np.full(config.HORIZON_DAYS, 5.0)
    r = simulate_series(fc, history=history, start_day=config.HORIZON_START_DAY)

    assert len(r.days) == config.HORIZON_DAYS
    assert r.days[0].day_id == 1942
    assert r.days[-1].day_id == 1969
    assert r.policy.lead_time_days == config.LEAD_TIME_DAYS
    assert r.policy.service_level == config.SERVICE_LEVEL
    assert r.policy.safety_stock == pytest.approx(0.0)
    assert r.policy.reorder_point == pytest.approx(70.0)     # 7x10 + 0
    assert r.policy.reorder_quantity == pytest.approx(70.0)
    assert r.policy.starting_inventory == pytest.approx(70.0)


# --------------------------------------------------------------------------- #
# Validation & edge cases
# --------------------------------------------------------------------------- #
def test_empty_forecast_raises():
    with pytest.raises(ValueError):
        simulate_series([], policy=_policy())


def test_negative_forecast_raises():
    with pytest.raises(ValueError):
        simulate_series([5.0, -1.0], policy=_policy())


def test_non_finite_forecast_raises():
    with pytest.raises(ValueError):
        simulate_series([5.0, np.nan], policy=_policy())
    with pytest.raises(ValueError):
        simulate_series([5.0, np.inf], policy=_policy())


def test_history_required_when_policy_missing():
    with pytest.raises(ValueError):
        simulate_series([5.0] * 28, history=None)


def test_lead_time_below_one_raises():
    with pytest.raises(ValueError):
        compute_policy([1.0, 2.0], lead_time_days=0.5)


def test_zero_history_zero_forecast_trace():
    # All-zero: policy zeros; nothing ordered, nothing lost, nothing held.
    p = _policy(expected_daily_demand=0.0, safety_stock=0.0,
                reorder_point=0.0, reorder_quantity=0.0,
                starting_inventory=0.0, lead_time_demand=0.0)
    r = simulate_series(np.zeros(28), policy=p, start_day=1942)

    assert len(r.days) == 28
    assert all(rec.on_hand == pytest.approx(0.0) for rec in r.days)
    assert all(rec.orders_placed == pytest.approx(0.0) for rec in r.days)
    assert not any(rec.projected_stockout for rec in r.days)
    assert all(rec.service_level_achieved == pytest.approx(1.0) for rec in r.days)
    assert r.service_level == 1.0
    assert r.fill_rate == 1.0
    assert r.final_on_order == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Provenance separation
# --------------------------------------------------------------------------- #
def test_all_records_are_simulated_provenance():
    p = _policy()
    r = simulate_series([5.0] * 28, policy=p, start_day=1942)
    assert all(rec.data_provenance == config.DATA_PROVENANCE_SIMULATED
               for rec in r.days)
    assert config.DATA_PROVENANCE_SIMULATED == "simulated"
    assert "observed" not in {rec.data_provenance for rec in r.days}


# --------------------------------------------------------------------------- #
# DDL-precision contract (NUMERIC(14,4); service_level NUMERIC(8,6))
# --------------------------------------------------------------------------- #
def test_records_rounded_to_ddl_precision():
    p = _policy()
    r = simulate_series([5.0] * 28, policy=p, start_day=1942)
    for rec in r.days:
        for field in ("starting_inventory", "demand_forecast", "lead_time_demand",
                      "safety_stock", "reorder_point", "inventory_position",
                      "on_hand", "orders_placed", "reorder_qty", "stockout_units",
                      "excess_inventory", "days_of_inventory"):
            assert round(getattr(rec, field), 4) == getattr(rec, field)
        assert round(rec.service_level_achieved, 6) == rec.service_level_achieved


# --------------------------------------------------------------------------- #
# Column contract with fact_inventory_simulation
# --------------------------------------------------------------------------- #
def test_record_fields_match_fact_inventory_simulation_columns():
    expected = {
        "day_id", "starting_inventory", "demand_forecast", "lead_time_demand",
        "safety_stock", "reorder_point", "inventory_position", "on_hand",
        "orders_placed", "reorder_qty", "projected_stockout", "stockout_units",
        "excess_inventory", "days_of_inventory", "service_level_achieved",
        "data_provenance",
    }
    assert set(record_field_names()) == expected
    # excluded DB-owned/introspection columns managed by the future driver
    db_owned = {"sim_id", "assumption_set_id", "product_surr_id", "store_surr_id"}
    assert not (expected & db_owned)


def test_record_data_provenance_default_is_simulated():
    assert DailySimulationRecord.__dataclass_fields__["data_provenance"].default \
        == config.DATA_PROVENANCE_SIMULATED