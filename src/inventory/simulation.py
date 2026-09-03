"""
Supply Chain & Demand Intelligence Platform
Phase 3E - Inventory simulation engine (pure, deterministic, DB-free).

Simulates ONE product-store series over a bounded daily horizon using the
locked assumption set (config.py) and the pure formulas/state-step functions
(formulas.py):

  - starting inventory        coverage rule (coverage days * expected daily)
  - forecast demand           per-day point forecast drives demand
  - lead time                 fixed (config.LEAD_TIME_DAYS)
  - safety stock              z(service_level) * sigma(lead-time demand)
  - reorder point             expected lead-time demand + safety stock
  - policy                    (s,Q): order Q when position <= reorder point
  - on-order inventory        orders scheduled for arrival lead_time days later
  - backorders                unmet demand carried forward (never lost)
  - stockouts                 projected per day as stockout_units
  - excess inventory          on-hand above excess coverage ceiling

Design rules:
  * DETERMINISTIC - no randomness, no I/O, no globals; identical inputs always
    produce identical results.
  * INDEPENDENTLY TESTABLE - the engine accepts an explicit InventoryPolicy or
    derives one from observed history; every daily record mirrors the
    fact_inventory_simulation columns (DDL precision NUMERIC(14,4), and
    NUMERIC(8,6) for service_level_achieved).
  * PROVENANCE SEPARATION - observed demand history is used ONLY to size the
    policy; the simulated horizon is driven by forecast demand. Every output
    record is labeled data_provenance='simulated' (config constant). No engine
    output can be 'observed'.
  * DRIVER-INDEPENDENT - no connection to fact_inventory_simulation here; a
    future driver maps SeriesSimulationResult rows into the DB.

Ordering within a simulated day (deterministic):
  1. apply replenishment arrivals due today (on_hand += qty, on_order -= qty)
  2. serve day's demand (+ carried backorder) - see formulas.advance_day
  3. if inventory position <= reorder point, place an order Q scheduled to
     arrive `lead_time_days` days later (on_order += Q)

Orders placed close to the horizon whose arrival falls after the last day
remain in on-order (reported as final_on_order / final_in_flight); they never
materialize inside this bounded window.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, fields
from typing import Deque, List, Optional, Sequence, Tuple, Union

import numpy as np

from . import config, formulas


# --------------------------------------------------------------------------- #
# Policy: the sizing parameters for one series under one assumption set
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class InventoryPolicy:
    """Per-series sizing under the locked assumption set (all SIMULATED)."""

    expected_daily_demand: float
    safety_stock: float
    reorder_point: float
    reorder_quantity: float
    starting_inventory: float
    lead_time_demand: float
    lead_time_days: float
    excess_coverage_days: float
    service_level: float


def policy_from_aggregates(
    expected_daily_demand: float,
    daily_sigma: float,
    *,
    service_level: float = config.SERVICE_LEVEL,
    lead_time_days: float = config.LEAD_TIME_DAYS,
    starting_coverage_days: float = config.STARTING_COVERAGE_DAYS,
    reorder_qty_multiple: float = config.REORDER_QTY_MULTIPLE,
    max_order_qty_coverage_days: float = config.MAX_ORDER_QTY_COVERAGE_DAYS,
    excess_coverage_days: float = config.EXCESS_COVERAGE_DAYS,
) -> InventoryPolicy:
    """Size a policy from pre-aggregated demand moments.

    Equivalent to compute_policy(history) when mean/std are computed over the
    same observed history, but accepts the per-series aggregates directly so the
    production driver never has to re-scan the 59M observed fact. All sizing
    formulas / rounding are delegated to formulas.py (identical results).
    """
    e = float(expected_daily_demand)
    if not math.isfinite(e) or e < 0:
        raise ValueError(f"expected_daily_demand must be finite and >= 0, got {expected_daily_demand!r}")
    safety = formulas.safety_stock(np.zeros(1), service_level, lead_time_days,
                                   sigma_override=daily_sigma)
    lt_demand = formulas.expected_lead_time_demand(np.asarray([e]), lead_time_days)
    rop = round(lt_demand + safety, 6)
    qty = formulas.reorder_quantity(
        np.zeros(1), expected_daily=e,
        multiple_days=reorder_qty_multiple,
        max_coverage_days=max_order_qty_coverage_days,
    )
    starting = round(starting_coverage_days * e, 6)
    return InventoryPolicy(
        expected_daily_demand=round(e, 6),
        safety_stock=safety,
        reorder_point=rop,
        reorder_quantity=qty,
        starting_inventory=starting,
        lead_time_demand=lt_demand,
        lead_time_days=float(lead_time_days),
        excess_coverage_days=excess_coverage_days,
        service_level=service_level,
    )


def compute_policy(
    history: Sequence[float],
    *,
    service_level: float = config.SERVICE_LEVEL,
    lead_time_days: float = config.LEAD_TIME_DAYS,
    estimator: str = config.DEMAND_CENTRAL_ESTIMATOR,
    starting_coverage_days: float = config.STARTING_COVERAGE_DAYS,
    reorder_qty_multiple: float = config.REORDER_QTY_MULTIPLE,
    max_order_qty_coverage_days: float = config.MAX_ORDER_QTY_COVERAGE_DAYS,
    excess_coverage_days: float = config.EXCESS_COVERAGE_DAYS,
    sigma_override: Optional[float] = None,
    ddof: int = 1,
) -> InventoryPolicy:
    """Derive an InventoryPolicy from observed demand history.

    All sizing formulas are those locked in config.py:
      expected_daily_demand   = formulas.expected_daily_demand(history)
      safety_stock            = z(service_level) * sigma_lead_time_demand
      lead_time_demand        = expected_daily * lead_time_days
      reorder_point           = lead_time_demand + safety_stock
      reorder_quantity        = (s,Q) multiple, capped by coverage
      starting_inventory      = starting_coverage_days * expected daily demand
    """
    h = np.asarray(history, dtype=np.float64).ravel()
    if h.size == 0:
        raise ValueError("history must not be empty")
    if not np.all(np.isfinite(h)):
        raise ValueError("history must contain only finite values")
    if np.any(h < 0):
        raise ValueError("history must be non-negative")
    expected_daily = formulas.expected_daily_demand(h, estimator=estimator)
    safety = formulas.safety_stock(
        h, service_level, lead_time_days, ddof=ddof, sigma_override=sigma_override
    )
    lt_demand = formulas.expected_lead_time_demand(h, lead_time_days, estimator=estimator)
    # reorder_point MUST honor sigma_override too, so the documented identity
    # reorder_point = lead_time_demand + safety_stock holds whenever the caller
    # supplies a daily-sigma override (e.g. the driver's aggregate sizing).
    rop = round(lt_demand + safety, 6)
    qty = formulas.reorder_quantity(
        h,
        expected_daily=expected_daily,
        multiple_days=reorder_qty_multiple,
        max_coverage_days=max_order_qty_coverage_days,
    )
    starting = formulas.starting_inventory_coverage(h, starting_coverage_days,
                                                    estimator=estimator)
    if lead_time_days < 1:
        raise ValueError("lead_time_days must be >= 1 for discrete arrival scheduling")
    return InventoryPolicy(
        expected_daily_demand=expected_daily,
        safety_stock=safety,
        reorder_point=rop,
        reorder_quantity=qty,
        starting_inventory=starting,
        lead_time_demand=lt_demand,
        lead_time_days=float(lead_time_days),
        excess_coverage_days=excess_coverage_days,
        service_level=service_level,
    )


# --------------------------------------------------------------------------- #
# Per-day record - mirrors fact_inventory_simulation (minus ids)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DailySimulationRecord:
    """One simulated day, column-aligned with fact_inventory_simulation.

    starting_inventory is the on-hand at the START of the day (before any
    replenishment arrival and before demand), so it equals the previous day's
    on_hand. NUMERIC(14,4) fields are rounded to 4 dp; service_level_achieved
    to 6 dp (NUMERIC(8,6)). data_provenance is ALWAYS
    config.DATA_PROVENANCE_SIMULATED.
    """

    day_id: int
    starting_inventory: float
    demand_forecast: float
    lead_time_demand: float
    safety_stock: float
    reorder_point: float
    inventory_position: float
    on_hand: float
    orders_placed: float
    reorder_qty: float
    projected_stockout: bool
    stockout_units: float
    excess_inventory: float
    days_of_inventory: float
    service_level_achieved: float
    data_provenance: str = config.DATA_PROVENANCE_SIMULATED


_R4 = lambda x: round(float(x), 4)  # noqa: E731  NUMERIC(14,4)
_R6 = lambda x: round(float(x), 6)  # noqa: E731  NUMERIC(8,6)


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeriesSimulationResult:
    """Full 28-day simulated trace for one series plus derived summary."""

    policy: InventoryPolicy
    days: Tuple[DailySimulationRecord, ...]
    final_backorder: float
    final_on_order: float

    @property
    def total_demand(self) -> float:
        return sum(r.demand_forecast for r in self.days)

    @property
    def stockout_days(self) -> int:
        return sum(1 for r in self.days if r.projected_stockout)

    @property
    def total_orders_placed(self) -> int:
        return int(round(sum(r.orders_placed for r in self.days)))

    @property
    def total_reorder_units(self) -> float:
        return sum(r.reorder_qty for r in self.days)

    @property
    def final_on_hand(self) -> float:
        return self.days[-1].on_hand

    @property
    def final_inventory_position(self) -> float:
        return self.days[-1].inventory_position

    @property
    def service_level(self) -> float:
        """Achieved CYCLE service level = 1 - stockout_days / horizon length.

        Matches the 'cycle service level' target in config and is free of the
        backorder double-count that affects a naive unit-sum. Returns 1.0 for a
        zero-length horizon.
        """
        n = len(self.days)
        if n == 0:
            return 1.0
        return 1.0 - self.stockout_days / n

    @property
    def fill_rate(self) -> float:
        """Share of horizon demand ultimately served from inventory by horizon end.

        sum(fulfilled) telescopes to sum(demand) - final_backorder (carried
        backorders are NOT double-counted here), so this is exact.
        """
        if self.total_demand <= 0:
            return 1.0
        return (self.total_demand - self.final_backorder) / self.total_demand

    # Order units still in flight at horizon end: arrivals beyond the last
    # simulated day => they never materialize inside this bounded window.
    @property
    def final_in_flight(self) -> float:
        return self.final_on_order


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def _validate_policy(policy: InventoryPolicy) -> None:
    """Reject invalid explicit policies (NaN/Inf/negative/disallowed levels).

    Guarantees the contract that no invalid numeric state can enter the
    simulation, whether the policy came from compute_policy or was supplied
    directly.
    """
    for name in ("expected_daily_demand", "safety_stock", "reorder_point",
                 "reorder_quantity", "starting_inventory", "lead_time_demand"):
        value = getattr(policy, name)
        if not math.isfinite(value):
            raise ValueError(f"policy.{name} must be finite, got {value!r}")
        if value < 0:
            raise ValueError(f"policy.{name} must be non-negative, got {value!r}")
    if policy.lead_time_days < 1 or not math.isfinite(policy.lead_time_days):
        raise ValueError(
            f"policy.lead_time_days must be finite and >= 1, got {policy.lead_time_days!r}")
    if policy.excess_coverage_days <= 0 or not math.isfinite(policy.excess_coverage_days):
        raise ValueError(
            "policy.excess_coverage_days must be finite and > 0, "
            f"got {policy.excess_coverage_days!r}")
    if not 0.0 < policy.service_level < 1.0:
        raise ValueError(f"policy.service_level must be in (0,1), got {policy.service_level!r}")


def simulate_series(
    forecast_demand: Sequence[float],
    *,
    policy: Optional[InventoryPolicy] = None,
    history: Optional[Sequence[float]] = None,
    start_day: int = config.HORIZON_START_DAY,
    service_level: float = config.SERVICE_LEVEL,
    lead_time_days: float = config.LEAD_TIME_DAYS,
    estimator: str = config.DEMAND_CENTRAL_ESTIMATOR,
    starting_coverage_days: float = config.STARTING_COVERAGE_DAYS,
    reorder_qty_multiple: float = config.REORDER_QTY_MULTIPLE,
    max_order_qty_coverage_days: float = config.MAX_ORDER_QTY_COVERAGE_DAYS,
    excess_coverage_days: float = config.EXCESS_COVERAGE_DAYS,
    sigma_override: Optional[float] = None,
    ddof: int = 1,
) -> SeriesSimulationResult:
    """Simulate one series over forecast_demand (default horizon [1942,1969]).

    Deterministic: same inputs => byte-identical trace.
    """
    demand = np.asarray(forecast_demand, dtype=np.float64).ravel()
    if demand.size == 0:
        raise ValueError("forecast_demand must not be empty")
    if not np.all(np.isfinite(demand)):
        raise ValueError("forecast_demand must contain only finite values")
    if np.any(demand < 0):
        raise ValueError("forecast_demand must be non-negative")

    if policy is None:
        if history is None:
            raise ValueError("history is required when policy is not provided")
        policy = compute_policy(
            history,
            service_level=service_level,
            lead_time_days=lead_time_days,
            estimator=estimator,
            starting_coverage_days=starting_coverage_days,
            reorder_qty_multiple=reorder_qty_multiple,
            max_order_qty_coverage_days=max_order_qty_coverage_days,
            excess_coverage_days=excess_coverage_days,
            sigma_override=sigma_override,
            ddof=ddof,
        )
    _validate_policy(policy)

    lead: int = int(round(policy.lead_time_days))
    on_hand: float = policy.starting_inventory
    on_order: float = 0.0
    backorder: float = 0.0
    pending: Deque[Tuple[int, float]] = deque()   # (arrival_day, qty), arrival-ordered

    expected_daily = policy.expected_daily_demand
    records: List[DailySimulationRecord] = []

    for i, d in enumerate(range(start_day, start_day + demand.size)):
        # Physical stock at the START of the day, before any replenishment
        # arrival (equals the previous day's end-of-day on_hand).
        start_on_hand = on_hand

        # 1. Replenishments arriving at the start of this day.
        while pending and pending[0][0] == d:
            _, qty = pending.popleft()
            on_hand += qty
            on_order -= qty

        # 2. Serve demand (+ carried backorder); possibly place an order.
        step = formulas.advance_day(
            on_hand=on_hand,
            on_order=on_order,
            backorder=backorder,
            demand=float(demand[i]),
            reorder_point_value=policy.reorder_point,
            order_qty=policy.reorder_quantity,
        )

        # 3. Schedule arrival for any newly placed order.
        if step.orders_placed > 0:
            pending.append((d + lead, step.order_qty))

        total = float(demand[i]) + backorder
        served = total - step.stockout_units
        service_achieved = served / total if total > 0 else 1.0

        # A stockout is recorded at the same DDL precision as the stored
        # stockout_units (NUMERIC(14,4)): a sub-4-dp unmet residual (float
        # accumulation noise) rounds to 0.0000 and must NOT contradict the
        # boolean flag. Keeps projected_stockout <=> stockout_units > 0.
        stockout_units_r4 = _R4(step.stockout_units)
        projected_stockout = stockout_units_r4 > 0.0

        rec = DailySimulationRecord(
            day_id=d,
            starting_inventory=_R4(start_on_hand),
            demand_forecast=_R4(float(demand[i])),
            lead_time_demand=_R4(policy.lead_time_demand),
            safety_stock=_R4(policy.safety_stock),
            reorder_point=_R4(policy.reorder_point),
            inventory_position=_R4(step.inventory_position),
            on_hand=_R4(step.on_hand),
            orders_placed=_R4(step.orders_placed),
            reorder_qty=_R4(step.order_qty),
            projected_stockout=projected_stockout,
            stockout_units=stockout_units_r4,
            excess_inventory=_R4(formulas.excess_inventory(
                step.on_hand, expected_daily, policy.excess_coverage_days)),
            days_of_inventory=_R4(formulas.days_of_inventory(
                step.on_hand, expected_daily)),
            service_level_achieved=_R6(service_achieved),
            data_provenance=config.DATA_PROVENANCE_SIMULATED,
        )
        records.append(rec)

        on_hand = step.on_hand
        on_order = step.on_order
        backorder = step.backorder

    return SeriesSimulationResult(
        policy=policy,
        days=tuple(records),
        final_backorder=backorder,
        final_on_order=on_order,
    )


# --------------------------------------------------------------------------- #
# Contract helpers
# --------------------------------------------------------------------------- #
def record_field_names() -> Tuple[str, ...]:
    """Field names a DailySimulationRecord persists to fact_inventory_simulation."""
    return tuple(f.name for f in fields(DailySimulationRecord))