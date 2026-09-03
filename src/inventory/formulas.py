"""
Supply Chain & Demand Intelligence Platform
Phase 3E - Inventory formulas (pure, deterministic).

Mathematically explicit safety-stock / reorder-point sizing and the rolling
inventory-position state update. These are PURE functions: no I/O, no globals,
no randomness, so every result is reproducible and unit-testable with
hand-computed cases.

Because the M5 dataset has NO observed inventory, every quantity computed here
is SIMULATED and must be stored/displayed with data_provenance='simulated'.

Definitions mirror docs/inventory_simulation_architecture.md and config.py:
  safety_stock      = z(service_level) * sigma(lead-time demand)
  sigma(lead-time)  = sigma(daily) * sqrt(lead_time_days)
  reorder_point     = expected lead-time demand + safety stock
  inventory position= on_hand + on_order - backorder
  reorder trigger   = position <= reorder_point
  excess inventory  = max(0, on_hand - excess_coverage_days * expected_daily_demand)
  days of inventory = on_hand / expected_daily_demand  (0 when expected demand ~ 0)
"""

from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------------------- #
# Demand-centrality and variability estimators (handle intermittency safely)
# --------------------------------------------------------------------------- #
def expected_daily_demand(history: np.ndarray, estimator: str = "mean") -> float:
    """Robust central tendency of daily demand.

    On sparse/intermittent M5 series a naive mean can be dwarfed by zeros, so
    we never divide by a near-zero mean downstream. estimator='mean' returns
    the arithmetic mean; estimator='median' returns the median. Both return 0.0
    only when the series is all-zero.
    """
    h = np.asarray(history, dtype=np.float64).ravel()
    if h.size == 0:
        return 0.0
    if estimator == "median":
        return float(np.median(h))
    return float(np.mean(h))


def daily_demand_sigma(history: np.ndarray, ddof: int = 1) -> float:
    """Volatility of daily demand (sigma of the demand series).

    Returns 0.0 for a constant or all-zero series (no measurable variability),
    so safety stock is 0 on perfectly smooth/zero series rather than 'nonsense'
    values. Never divides by zero.
    """
    h = np.asarray(history, dtype=np.float64).ravel()
    if h.size < 2:
        return 0.0
    # ddof=1 sample std, but for an all-zero/constant input the result is 0.0
    s = float(np.std(h, ddof=ddof))
    if not math.isfinite(s) or s < 0:
        return 0.0
    return s


def mean_absolute_demand(history: np.ndarray) -> float:
    """Mean absolute daily demand; robust when forecasting into zero-heavy data.

    Synonym for expected_daily_demand(..., estimator='mean'), provided so the
    simulation can rely on one documented estimator.
    """
    return expected_daily_demand(history, estimator="mean")


# --------------------------------------------------------------------------- #
# Safety stock / reorder point (explicit formulas)
# --------------------------------------------------------------------------- #
def z_service(service_level: float) -> float:
    """Standard-normal quantile for a cycle service level.

    Uses the explicit constant from config when the level equals it, otherwise
    a deterministic inverse-normal approximation. Throws on levels outside
    (0,1).
    """
    if not 0.0 < service_level < 1.0:
        raise ValueError("service_level must be in (0,1)")
    from . import config
    if abs(service_level - config.SERVICE_LEVEL) < 1e-12:
        return config.SERVICE_LEVEL_Z
    # Acklam's inverse normal CDF approximation (deterministic).
    a = [0.0, -3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0]
    b = [0.0, -5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [0.0, -7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
         -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0]
    d = [0.0, 7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0,
         3.754408661907416e0]
    p_low, p_high = 0.02425, 1.0 - 0.02425
    p = float(service_level)
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[1] * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) * q + c[6]) \
            / ((((d[1] * q + d[2]) * q + d[3]) * q + d[4]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[1] * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * r + a[6]) * q \
            / (((((b[1] * r + b[2]) * r + b[3]) * r + b[4]) * r + b[5]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[1] * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) * q + c[6]) \
            / ((((d[1] * q + d[2]) * q + d[3]) * q + d[4]) * q + 1.0)
    return x


def sigma_lead_time_demand(daily_sigma: float, lead_time_days: float) -> float:
    """sigma(lead-time demand) = sigma(daily) * sqrt(lead_time)."""
    if daily_sigma is None or not math.isfinite(daily_sigma) or daily_sigma < 0:
        return 0.0
    lt = max(float(lead_time_days), 0.0)
    return daily_sigma * math.sqrt(lt)


def safety_stock(
    history: np.ndarray,
    service_level: float,
    lead_time_days: float,
    ddof: int = 1,
    *,
    sigma_override: float | None = None,
) -> float:
    """safety_stock = z(service_level) * sigma(lead-time demand).

    Hand-computable:
      z = z_service(service_level)
      daily_sigma = sigma_override if provided else daily_demand_sigma(history)
      sigma_lt = daily_sigma * sqrt(lead_time_days)
      ss = z * sigma_lt
    On zero/constant demand (daily_sigma == 0) the result is 0.0 (no buffer
    needed for a perfectly smooth series).
    """
    z = z_service(service_level)
    if sigma_override is not None:
        daily_sigma = float(sigma_override)
    else:
        daily_sigma = daily_demand_sigma(history, ddof=ddof)
    return round(float(z * sigma_lead_time_demand(daily_sigma, lead_time_days)), 6)


def expected_lead_time_demand(history: np.ndarray, lead_time_days: float,
                              estimator: str = "mean") -> float:
    """expected demand over the lead time = expected_daily * lead_time."""
    daily = expected_daily_demand(history, estimator=estimator)
    return daily * max(float(lead_time_days), 0.0)


def reorder_point(history: np.ndarray, service_level: float, lead_time_days: float,
                  estimator: str = "mean", ddof: int = 1) -> float:
    """reorder_point = expected lead-time demand + safety stock (rounded)."""
    lt_demand = expected_lead_time_demand(history, lead_time_days, estimator)
    ss = safety_stock(history, service_level, lead_time_days, ddof)
    return round(lt_demand + ss, 6)


# --------------------------------------------------------------------------- #
# Reorder quantity
# --------------------------------------------------------------------------- #
def reorder_quantity(history: np.ndarray, expected_daily: float | None = None,
                     multiple_days: float = 7.0,
                     max_coverage_days: float = 28.0) -> float:
    """Reorder quantity Q under the (s,Q) policy.

    Q = multiple_days * expected_daily, capped at max_coverage_days *
    expected_daily. If expected_daily <= 0 (all-zero series) Q = 0 (nothing to
    reorder).
    """
    if expected_daily is None:
        expected_daily = expected_daily_demand(history)
    e = float(expected_daily)
    if e <= 0:
        return 0.0
    q = multiple_days * e
    cap = max_coverage_days * e
    return round(max(0.0, min(q, cap)), 6)


# --------------------------------------------------------------------------- #
# Rolling inventory-position state machine (pure per-day step)
# --------------------------------------------------------------------------- #
def starting_inventory_coverage(history: np.ndarray, coverage_days: float,
                                estimator: str = "mean") -> float:
    """Starting on-hand = coverage_days * expected daily demand (rounded)."""
    return round(coverage_days * expected_daily_demand(history, estimator), 6)


def reorder_trigger(inventory_position: float, reorder_point_value: float) -> bool:
    """True when position <= reorder point (place an order)."""
    return float(inventory_position) <= float(reorder_point_value)


class InventoryStep:
    """One simulated day's outcome (immutable value object)."""

    __slots__ = ("on_hand", "on_order", "backorder", "inventory_position",
                 "demand", "stockout_units", "stockout", "order_qty",
                 "orders_placed")

    def __init__(self, on_hand, on_order, backorder, inventory_position,
                 demand, stockout_units, stockout, order_qty, orders_placed):
        self.on_hand = float(on_hand)
        self.on_order = float(on_order)
        self.backorder = float(backorder)
        self.inventory_position = float(inventory_position)
        self.demand = float(demand)
        self.stockout_units = float(stockout_units)
        self.stockout = bool(stockout)
        self.order_qty = float(order_qty)
        self.orders_placed = float(orders_placed)


def advance_day(
    on_hand: float,
    on_order: float,
    backorder: float,
    demand: float,
    reorder_point_value: float,
    order_qty: float,
) -> InventoryStep:
    """Advance the rolling inventory state by one simulated day.

    Sequence (deterministic, single-day, hand-tested):
      1. total demand to satisfy = demand + prior backorder
      2. fulfilled = min(on_hand, total); unmet -> new backorder (carried)
      3. on_hand -= fulfilled; if unmet > 0 stockout_units = unmet
      4. inventory position = on_hand + on_order - backorder
      5. if position <= reorder point and order_qty > 0: place order
         (on_order += order_qty; order_qty recorded)

    Lead-time arrival scheduling (decrementing on_order as replenishments
    land) is handled by the driver across days; this pure function computes a
    single day's end state plus that day's demand-satisfaction and reorder
    activity.

    Returns an InventoryStep with the end-of-day state plus the day's activity.
    """
    demand = max(float(demand), 0.0)
    on_hand = float(on_hand)
    on_order = float(on_order)
    backorder = float(backorder)
    total = demand + backorder
    fulfilled = min(on_hand, total)
    unmet = total - fulfilled
    on_hand -= fulfilled
    new_backorder = unmet

    position = on_hand + on_order - new_backorder

    placed = 0.0
    if position <= reorder_point_value and order_qty > 0:
        on_order += order_qty
        placed = order_qty
        position = on_hand + on_order - new_backorder

    return InventoryStep(
        on_hand=on_hand,
        on_order=on_order,
        backorder=new_backorder,
        inventory_position=position,
        demand=demand,
        stockout_units=unmet if unmet > 0 else 0.0,
        stockout=unmet > 0,
        order_qty=placed,
        orders_placed=1.0 if placed > 0 else 0.0,
    )


# --------------------------------------------------------------------------- #
# Post-hoc metrics derived from a simulated day
# --------------------------------------------------------------------------- #
def excess_inventory(on_hand: float, expected_daily: float,
                     excess_coverage_days: float) -> float:
    """excess = max(0, on_hand - excess_coverage_days * expected_daily)."""
    if expected_daily <= 0:
        return 0.0
    ceiling = excess_coverage_days * expected_daily
    return round(max(0.0, float(on_hand) - ceiling), 6)


def days_of_inventory(on_hand: float, expected_daily: float) -> float:
    """Days of inventory = on_hand / expected_daily (0 when expected demand ~ 0)."""
    if expected_daily <= 0:
        return 0.0
    return round(float(on_hand) / expected_daily, 6)
