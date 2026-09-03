"""
Phase 3E - Simulation contract tests (step 4).

Independent, output-derived verification of the simulate_series() contract:

  1.  Input/output schema (types, shapes, properties).
  2.  Exact 28-day horizon 1942-1969 in the production configuration.
  3.  Forecast demand drives the simulated horizon; observed history only
      sizes the policy (never the day-by-day trace).
  4.  Every output carries data_provenance='simulated'.
  5.  Deterministic / reproducible output.
  6.  State invariants (start-of-day carry, on_hand / on_order / backorder
      internal consistency) - checked WITHOUT re-running the engine, by
      reconstructing the shadow state from the emitted records.
  7.  Lead-time arrival behavior (no premature, no phantom arrivals).
  8.  Reorder trigger and (s,Q) behavior.
  9.  Backorder / stockout handling.
  10. Out-of-horizon orders stay in-flight (never counted as received).
  11. NaN / Inf / negative / empty inputs rejected.
  12. Idempotent deterministic behavior suitable for later batch DB writes.
  13. Output fields match the intended fact_inventory_simulation contract.

No database is involved; the engine is never asked to run the 30,490-series
set or the bounded pilot.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.inventory import config
from src.inventory.simulation import (
    DailySimulationRecord,
    InventoryPolicy,
    SeriesSimulationResult,
    compute_policy,
    policy_from_aggregates,
    record_field_names,
    simulate_series,
)


def _policy(**overrides):
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


# =========================================================================== #
# 1. Input/output schema
# =========================================================================== #
def test_return_shapes_and_types():
    r = simulate_series(np.full(28, 5.0), policy=_policy(), start_day=1942)
    assert isinstance(r, SeriesSimulationResult)
    assert isinstance(r.policy, InventoryPolicy)
    assert isinstance(r.days, tuple)
    assert all(isinstance(d, DailySimulationRecord) for d in r.days)
    assert len(r.days) == 28                      # 1 record per forecast day
    # default policy starts with 3 units against demand 5 -> day-1 fill ratio 3/5
    assert r.days[0].service_level_achieved == pytest.approx(0.6)


def test_forecast_length_preserved_and_scalarized():
    gen = np.array([[1.0], [2.0], [3.0]], dtype=float)   # 2-D input must be raveled
    r = simulate_series(gen, policy=_policy(), start_day=1942)
    assert len(r.days) == 3
    assert [d.demand_forecast for d in r.days] == pytest.approx([1.0, 2.0, 3.0])


# =========================================================================== #
# 2. Exact 28-day horizon: 1942-1969 (production configuration)
# =========================================================================== #
def test_exact_horizon_days_1942_to_1969():
    assert config.HORIZON_DAYS == 28
    assert config.HORIZON_START_DAY == 1942
    assert config.HORIZON_END_DAY == 1969
    r = simulate_series(np.full(config.HORIZON_DAYS, 5.0),
                        history=np.full(28, 10.0))
    assert [d.day_id for d in r.days] == list(range(1942, 1970))
    next_expected = None
    for d in r.days:
        assert d.day_id == (next_expected if next_expected is not None else 1942)
        next_expected = d.day_id + 1


# =========================================================================== #
# 3. Forecast drives horizon; history only sizes the policy
# =========================================================================== #
def test_forecast_demand_drives_horizon():
    r = simulate_series([1.0, 2.0, 10.0], policy=_policy(), start_day=1942)
    assert [d.demand_forecast for d in r.days] == pytest.approx([1.0, 2.0, 10.0])
    # lead-time-demand/safety/reorder_point are policy-derived, not per-day
    assert all(d.lead_time_demand == r.policy.lead_time_demand for d in r.days)
    assert all(d.safety_stock == r.policy.safety_stock for d in r.days)
    assert all(d.reorder_point == r.policy.reorder_point for d in r.days)


def test_history_only_sizes_policy_not_trace():
    # Identical explicit policy + identical forecast, but very different
    # observed histories => byte-identical trace (history is ignored because
    # an explicit policy is authoritative).
    fc = np.full(28, 5.0)
    p = _policy()
    a = simulate_series(fc, policy=p, history=np.full(100, 1.0), start_day=1942)
    b = simulate_series(fc, policy=p, history=np.full(100, 1000.0), start_day=1942)
    assert a.days == b.days
    assert a.days == b.days


def test_history_changes_derived_policy_only():
    # Without an explicit policy, different histories produce different sizing
    # but both must simulate over the SAME forecast window.
    fc = np.full(28, 5.0)
    low = simulate_series(fc, history=np.full(100, 1.0), start_day=1942)
    high = simulate_series(fc, history=np.full(100, 50.0), start_day=1942)
    assert low.policy != high.policy
    assert low.policy.starting_inventory < high.policy.starting_inventory
    assert [d.day_id for d in low.days] == [d.day_id for d in high.days]


# =========================================================================== #
# 4. Provenance
# =========================================================================== #
def test_every_output_is_simulated_provenance():
    assert config.DATA_PROVENANCE_SIMULATED == "simulated"
    r = simulate_series(np.full(28, 5.0),
                        history=np.full(28, 10.0))
    assert all(d.data_provenance == "simulated" for d in r.days)
    assert not any(d.data_provenance == "observed" for d in r.days)
    assert r.policy  # policy is itself a simulated quantity container


# =========================================================================== #
# 5. Determinism / reproducibility
# =========================================================================== #
def test_deterministic_across_call_formats():
    fc = np.full(28, 5.0)
    p = _policy()
    a = simulate_series(list(fc), policy=p, start_day=1942)
    b = simulate_series(tuple(fc), policy=p, start_day=1942)
    c = simulate_series(fc, policy=p, start_day=1942)
    assert a.days == b.days == c.days
    assert a.final_on_order == b.final_on_order == c.final_on_order
    assert a.service_level == b.service_level
    assert a.fill_rate == b.fill_rate


# =========================================================================== #
# 6. State invariants (reconstructed from emitted records, engine not re-run)
# =========================================================================== #
TOL = 1e-2


def _assert_state_invariants(r: SeriesSimulationResult) -> None:
    """Replay the state machine purely from the records and assert consistency."""
    assert len(r.days) >= 1
    lead = int(round(r.policy.lead_time_days))
    expected_arrivals = {}            # day_id -> total qty due that day
    on_order_prev = 0.0

    for i, rec in enumerate(r.days):
        assert rec.on_hand >= 0
        assert rec.stockout_units >= 0
        assert rec.reorder_qty >= 0
        assert rec.orders_placed in (0.0, 1.0)
        if rec.projected_stockout:
            assert rec.stockout_units > 0
        else:
            assert rec.stockout_units == pytest.approx(0.0, abs=TOL)

        backorder_start = r.days[i - 1].stockout_units if i > 0 else 0.0
        fulfilled = rec.demand_forecast + backorder_start - rec.stockout_units
        assert fulfilled >= 0

        # on_hand_end = start_on_hand + arrivals - fulfilled  =>  arrivals
        arrivals = rec.on_hand - rec.starting_inventory + fulfilled
        assert arrivals >= -TOL
        expected = expected_arrivals.get(rec.day_id, 0.0)
        assert arrivals == pytest.approx(expected, abs=TOL)

        # inventory_position = on_hand + on_order - backorder_end
        on_order_end = on_order_prev - arrivals + rec.reorder_qty
        assert on_order_end >= -TOL
        derived_position = rec.on_hand + on_order_end - rec.stockout_units
        assert rec.inventory_position == pytest.approx(derived_position, abs=TOL)

        # the day's order (if any) must eventually arrive at day+lead
        if rec.orders_placed > 0:
            assert rec.reorder_qty > 0
            arrival_day = rec.day_id + lead
            expected_arrivals[arrival_day] = (
                expected_arrivals.get(arrival_day, 0.0) + rec.reorder_qty)
        else:
            assert rec.reorder_qty == pytest.approx(0.0, abs=TOL)

        on_order_prev = on_order_end

    assert r.final_on_order == pytest.approx(on_order_prev, abs=TOL)
    assert r.final_backorder == pytest.approx(r.days[-1].stockout_units, abs=TOL)


@pytest.mark.parametrize("lead", [1, 3, 7])
def test_state_invariants_across_lead_times(lead):
    p = _policy(lead_time_days=float(lead))
    r = simulate_series(np.full(28, 5.0), policy=p, start_day=1942)
    _assert_state_invariants(r)


def test_state_invariants_zero_series():
    r = simulate_series(np.zeros(28),
                        policy=_policy(expected_daily_demand=0.0,
                                       safety_stock=0.0, reorder_point=0.0,
                                       reorder_quantity=0.0,
                                       starting_inventory=0.0,
                                       lead_time_demand=0.0))
    _assert_state_invariants(r)


def test_state_invariants_with_demand_spikes():
    # Demand spikes far above starting stock push deep into backorder.
    fc = np.array([2.0, 100.0, 3.0, 200.0, 1.0, 0.0] * 5)
    r = simulate_series(fc, policy=_policy(), start_day=1942)
    _assert_state_invariants(r)
    assert r.stockout_days > 0
    assert r.final_backorder >= 0


def test_next_day_starting_inventory_equals_prev_day_on_hand():
    fc = np.full(28, 5.0)
    r = simulate_series(fc, policy=_policy(), start_day=1942)
    for prev, nxt in zip(r.days, r.days[1:]):
        assert nxt.starting_inventory == pytest.approx(prev.on_hand, abs=TOL)


# =========================================================================== #
# 7. Lead-time arrival behavior
# =========================================================================== #
def test_no_premature_arrival_before_lead_time():
    # 1 order placed day 1942 (lead 3), zero demand: on_hand must stay flat on
    # days -1..+2 of the arrival and jump only at day 1942+3=1945.
    p = _policy(starting_inventory=1.0, reorder_point=1000.0,
                reorder_quantity=25.0, lead_time_days=3.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)
    on_hands = [d.on_hand for d in r.days]
    assert [d.day_id for d in r.days] == [1942, 1943, 1944, 1945, 1946]
    assert on_hands[0] == pytest.approx(1.0)
    assert on_hands[1] == pytest.approx(1.0)      # no arrival yet
    assert on_hands[2] == pytest.approx(1.0)      # no arrival yet
    assert on_hands[3] == pytest.approx(26.0)     # order from 1942+3 lands
    _assert_state_invariants(r)


# =========================================================================== #
# 8. Reorder trigger and (s,Q) behavior
# =========================================================================== #
def test_trigger_at_position_equal_to_reorder_point():
    # Pre-order position == reorder point (boundary) must still trigger. The
    # recorded inventory_position is the END-OF-DAY value (after the order),
    # so it equals 10 + 40 = 50.
    p = _policy(starting_inventory=10.0, reorder_point=10.0,
                reorder_quantity=40.0, lead_time_days=7.0)
    r = simulate_series([0.0, 0.0], policy=p, start_day=1942)
    d1 = r.days[0]
    assert d1.inventory_position == pytest.approx(50.0)   # 10 (pre) + 40 (order)
    assert d1.orders_placed == pytest.approx(1.0)
    assert d1.reorder_qty == pytest.approx(40.0)


def test_no_trigger_above_reorder_point():
    p = _policy(starting_inventory=11.0, reorder_point=10.0,
                reorder_quantity=40.0, lead_time_days=7.0)
    r = simulate_series([0.0], policy=p, start_day=1942)
    assert r.days[0].orders_placed == pytest.approx(0.0)
    assert r.days[0].reorder_qty == pytest.approx(0.0)


def test_trigger_below_reorder_point():
    p = _policy(starting_inventory=9.0, reorder_point=10.0,
                reorder_quantity=40.0, lead_time_days=7.0)
    r = simulate_series([0.0], policy=p, start_day=1942)
    assert r.days[0].orders_placed == pytest.approx(1.0)
    assert r.days[0].reorder_qty == pytest.approx(40.0)


def test_sq_policy_orders_fixed_quantity_regardless_of_deficit():
    # (s,Q): fixed Q each time, independent of how far position sits below s.
    p = _policy(starting_inventory=1.0, reorder_point=1000.0,
                reorder_quantity=20.0, lead_time_days=7.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)
    assert r.total_orders_placed == 5
    assert [d.reorder_qty for d in r.days] == pytest.approx([20.0] * 5)


def test_no_order_when_quantity_zero():
    p = _policy(reorder_quantity=0.0, reorder_point=10.0,
                starting_inventory=1.0, lead_time_days=7.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)
    assert all(d.orders_placed == pytest.approx(0.0) for d in r.days)


# =========================================================================== #
# 9. Backorder / stockout handling
# =========================================================================== #
def test_backorder_carried_until_replenishment():
    p = _policy()  # starting=3, rop=5, qty=50, lead=7
    r = simulate_series(np.full(28, 5.0), policy=p, start_day=1942)
    # day 1943: carried backorder of 2 is part of the 7-unit shortfall
    second = r.days[1]
    assert second.day_id == 1943
    assert second.stockout_units == pytest.approx(7.0)
    # on the arrival day (1949) the 32-unit backlog is cleared BEFORE nothing
    # new is lost; service level achieved jumps to 1.0
    arrival = r.days[7]
    assert arrival.day_id == 1949
    assert arrival.service_level_achieved == pytest.approx(1.0)
    assert arrival.projected_stockout is False


def test_fill_rate_telescoping_identity():
    # sum(fulfilled) = total_demand - final_backorder (no double count).
    r = simulate_series(np.full(28, 5.0), policy=_policy(), start_day=1942)
    assert r.fill_rate == pytest.approx((r.total_demand - r.final_backorder)
                                        / r.total_demand)
    assert 0.0 <= r.fill_rate <= 1.0


def test_stockout_units_are_that_days_shortfall():
    p = _policy()
    r = simulate_series([3.0, 0.0], policy=p, start_day=1942)
    # day1: exactly 3 served from stock of 3 -> no shortfall
    assert r.days[0].stockout_units == pytest.approx(0.0)
    assert r.days[0].service_level_achieved == pytest.approx(1.0)


# =========================================================================== #
# 10. Out-of-horizon orders never counted as received
# =========================================================================== #
def test_out_of_horizon_orders_stay_in_flight():
    # 5 x 10-unit orders placed with lead 7 over a 5-day horizon: every arrival
    # day (1949..1953) lies beyond the last simulated day (1946).
    p = _policy(starting_inventory=1.0, reorder_point=1000.0,
                reorder_quantity=10.0, lead_time_days=7.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)
    assert r.days[-1].day_id == 1946
    assert r.total_orders_placed == 5
    assert r.final_on_order == pytest.approx(50.0)
    assert r.final_in_flight == pytest.approx(50.0)
    assert all(d.on_hand == pytest.approx(1.0) for d in r.days)  # nothing landed
    _assert_state_invariants(r)


def test_partial_in_horizon_arrival_never_exceeds_pending():
    # lead=2: orders land at day+2. In-horizon arrivals: 1944 (from 1942),
    # 1945 (from 1943), 1946 (from 1944); the day-1945 order arrives 1947
    # (out of the 5-day window).
    p = _policy(starting_inventory=1.0, reorder_point=1000.0,
                reorder_quantity=30.0, lead_time_days=2.0)
    r = simulate_series([0.0] * 5, policy=p, start_day=1942)
    on_hands = [d.on_hand for d in r.days]
    assert on_hands == pytest.approx([1.0, 1.0, 31.0, 61.0, 91.0])
    assert r.days[2].day_id == 1944 and on_hands[2] == pytest.approx(31.0)
    assert r.days[4].day_id == 1946 and on_hands[4] == pytest.approx(91.0)
    _assert_state_invariants(r)


# =========================================================================== #
# 11. Invalid inputs rejected
# =========================================================================== #
def test_invalid_forecast_inputs_rejected():
    for bad in ([], [5.0, -1.0], [np.nan], [np.inf], [-np.inf], [0.0, np.nan, 1.0]):
        with pytest.raises(ValueError):
            simulate_series(bad, policy=_policy())


def test_invalid_history_inputs_rejected_when_deriving_policy():
    for bad in ([], [1.0, -2.0], [np.nan, 1.0], [np.inf, 1.0]):
        with pytest.raises(ValueError):
            simulate_series([5.0] * 28, history=bad)


def test_invalid_explicit_policy_rejected():
    fc = [5.0] * 28
    bad_policies = [
        _policy(expected_daily_demand=np.nan),
        _policy(reorder_point=np.inf),
        _policy(safety_stock=-1.0),
        _policy(starting_inventory=-5.0),
        _policy(lead_time_days=0.0),
        _policy(excess_coverage_days=0.0),
        _policy(service_level=0.0),
        _policy(service_level=1.0),
    ]
    for p in bad_policies:
        with pytest.raises(ValueError):
            simulate_series(fc, policy=p)


# =========================================================================== #
# 12. Idempotent deterministic behavior for batch writes
# =========================================================================== #
def test_idempotent_across_repeated_and_interleaved_runs():
    # Simulate several distinct series sequentially and interleaved; repeated
    # calls must reproduce byte-identical traces (no shared mutable state).
    policies = [
        _policy(),
        _policy(starting_inventory=20.0, reorder_point=15.0,
                reorder_quantity=80.0, lead_time_days=7.0),
        _policy(starting_inventory=2.0, reorder_point=3.0,
                reorder_quantity=20.0, lead_time_days=2.0),
    ]
    forecasts = [np.full(28, k) for k in (5.0, 3.0, 7.0)]
    first_pass = [simulate_series(f, policy=p, start_day=1942)
                  for f, p in zip(forecasts, policies)]
    # interleave a second batch (reverse order) to prove no cross-talk
    second_pass = [simulate_series(f, policy=p, start_day=1942)
                   for f, p in zip(forecasts, policies)]
    for a, b in zip(first_pass, second_pass):
        assert a.days == b.days
        assert a.final_on_order == b.final_on_order
        assert a.final_backorder == b.final_backorder
        assert a.service_level == b.service_level
        assert a.policy == b.policy


# =========================================================================== #
# 13. Output fields match fact_inventory_simulation contract
# =========================================================================== #
def test_record_fields_exactly_match_fact_inventory_simulation_columns():
    # Column order follows 02_facts.sql for fact_inventory_simulation, minus
    # DB-owned identity/FK columns (sim_id, assumption_set_id,
    # product_surr_id, store_surr_id) managed by the future driver.
    expected_order = [
        "day_id", "starting_inventory", "demand_forecast", "lead_time_demand",
        "safety_stock", "reorder_point", "inventory_position", "on_hand",
        "orders_placed", "reorder_qty", "projected_stockout", "stockout_units",
        "excess_inventory", "days_of_inventory", "service_level_achieved",
        "data_provenance",
    ]
    assert list(record_field_names()) == expected_order
    assert set(record_field_names()) == set(expected_order)


def test_record_field_types_match_contract():
    r = simulate_series(np.full(28, 5.0), policy=_policy(), start_day=1942)
    for d in r.days:
        assert isinstance(d.day_id, int)
        assert isinstance(d.data_provenance, str)
        assert isinstance(d.projected_stockout, bool)
        for f in ("starting_inventory", "demand_forecast", "lead_time_demand",
                  "safety_stock", "reorder_point", "inventory_position",
                  "on_hand", "orders_placed", "reorder_qty", "stockout_units",
                  "excess_inventory", "days_of_inventory"):
            assert isinstance(getattr(d, f), float)
        assert isinstance(d.service_level_achieved, float)
        # DDL precision: NUMERIC(14,4) and NUMERIC(8,6)
        for f in ("starting_inventory", "demand_forecast", "lead_time_demand",
                  "safety_stock", "reorder_point", "inventory_position",
                  "on_hand", "orders_placed", "reorder_qty", "stockout_units",
                  "excess_inventory", "days_of_inventory"):
            assert round(getattr(d, f), 4) == getattr(d, f)
        assert round(d.service_level_achieved, 6) == d.service_level_achieved


# =========================================================================== #
# 14. Policy sizing: sigma_override consistency + aggregate sizing helper
# =========================================================================== #
def test_sigma_override_keeps_reorder_point_consistent():
    # reorder_point = lead_time_demand + safety_stock must hold even when the
    # daily-sigma override differs from the sample sigma of the history used.
    history = np.full(28, 10.0)          # sample std = 0 -> naive safety stock 0
    p = compute_policy(history, sigma_override=3.0)
    expected_safety = config.SERVICE_LEVEL_Z * 3.0 * np.sqrt(config.LEAD_TIME_DAYS)
    assert p.safety_stock == pytest.approx(expected_safety)
    # regression guard: previously reorder_point ignored the override and
    # silently recomputed sigma from history
    assert p.reorder_point == pytest.approx(p.lead_time_demand + p.safety_stock)


def test_policy_from_aggregates_matches_compute_policy():
    history = np.array([4.0, 6.0, 5.0, 8.0, 3.0, 5.0, 7.0, 4.0, 6.0, 5.0] * 30)
    mean, std = float(np.mean(history)), float(np.std(history, ddof=1))
    via_history = compute_policy(history, sigma_override=std)
    via_agg = policy_from_aggregates(mean, std)
    assert via_agg.expected_daily_demand == pytest.approx(via_history.expected_daily_demand)
    assert via_agg.safety_stock == pytest.approx(via_history.safety_stock)
    assert via_agg.reorder_point == pytest.approx(via_history.reorder_point)
    assert via_agg.reorder_quantity == pytest.approx(via_history.reorder_quantity)
    assert via_agg.starting_inventory == pytest.approx(via_history.starting_inventory)
    assert via_agg.lead_time_demand == pytest.approx(via_history.lead_time_demand)


def test_policy_from_aggregates_produces_valid_simulation():
    p = policy_from_aggregates(expected_daily_demand=5.0, daily_sigma=2.0)
    r = simulate_series(np.full(28, 5.0), policy=p, start_day=1942)
    assert len(r.days) == 28
    assert all(d.data_provenance == config.DATA_PROVENANCE_SIMULATED for d in r.days)
    assert r.days[0].lead_time_demand == pytest.approx(round(p.lead_time_demand, 4))
    assert r.days[0].safety_stock == pytest.approx(round(p.safety_stock, 4))
    assert r.days[0].reorder_point == pytest.approx(round(p.reorder_point, 4))


def test_policy_from_aggregates_rejects_negative_mean():
    with pytest.raises(ValueError):
        policy_from_aggregates(-1.0, 0.0)


def test_projected_stockout_matches_stored_precision():
    # A sub-4dp unmet residual (float noise on healthy series) must not flag a
    # stockout: the stored contract is projected_stockout <=> stockout_units>0
    # at the DDL precision (NUMERIC(14,4)).
    p = _policy(starting_inventory=5.0, reorder_point=0.0,
                reorder_quantity=0.0)          # no reorders: on_hand only decays
    # day 1942 consumes 5.0 exactly (no residual); day 1943 unmet is 1e-5 which
    # rounds to 0.0000 at 4dp -> must NOT be flagged as a stockout.
    r = simulate_series([5.0, 1e-5] + [1e-5] * 26, policy=p, start_day=1942)
    stockout_recs = [d for d in r.days if d.stockout_units > 0.0]
    assert all(d.projected_stockout for d in stockout_recs)
    flagged = [d for d in r.days if d.projected_stockout]
    assert all(d.stockout_units > 0.0 for d in flagged)
    assert not r.days[1].projected_stockout     # 1e-5 -> 0.0000 at NUMERIC(14,4)
    assert r.days[1].stockout_units == pytest.approx(0.0)