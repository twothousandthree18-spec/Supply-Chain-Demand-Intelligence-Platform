"""Phase 6 inventory data-access service.

Reads the bounded 28-day `fact_inventory_simulation` (horizon 1942..1969, one
assumption set) and the baseline `assumption_set` policy. All figures are
simulated (never presented as observed). Endpoints are bounded: a single-pass
aggregate summary, a per-series 28-day horizon, and the static policy snapshot.
No inventory math is recomputed in the web layer.
"""

from ..contracts.common import Provenance
from ..contracts.dashboard import (
    DatabaseKey,
    InventoryDay,
    InventoryHorizon,
    InventoryPolicy,
    InventorySummary,
)
from .db import parse_series


def _baseline_run(cur) -> int | None:
    """Resolve the baseline scenario run id (scenario named 'baseline')."""
    cur.execute(
        """
        SELECT r.scenario_run_id
        FROM fact_scenario_run r
        JOIN scenario s ON s.scenario_id = r.scenario_id
        WHERE lower(s.scenario_name) IN ('baseline')
        ORDER BY r.scenario_run_id
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return row[0] if row else None


def summary(cur) -> InventorySummary:
    """Aggregate baseline simulated inventory state (bounded, one pass).

    The horizon table carries per-day position/on-hand/on-order/service/safety/
    reorder; the baseline scenario run carries the end-of-horizon final on-hand/
    on-order/backorder + fill-rate which the daily sim does not store. Both are
    simulated.
    """
    base = _baseline_run(cur)
    cur.execute(
        """
        SELECT AVG(service_level_achieved)::float8,
               AVG(fill_rate)::float8,
               SUM(stockout_units)::float8,
               SUM(total_excess_units)::float8,
               AVG(avg_days_of_inventory)::float8,
               AVG(safety_stock)::float8,
               AVG(reorder_point)::float8,
               SUM(final_on_hand)::float8,
               SUM(final_on_order)::float8,
               SUM(final_backorder)::float8,
               SUM(avg_inventory_position)::float8
        FROM fact_scenario_result
        WHERE scenario_run_id = %s
        """,
        (base,),
    )
    r = cur.fetchone() if base else None

    cur.execute(
        "SELECT COUNT(DISTINCT day_id) FROM fact_inventory_simulation"
    )
    horizon_days = int(cur.fetchone()[0] or 0)

    if r is None:
        return InventorySummary(horizon_days=horizon_days, provenance=Provenance.SIMULATED)

    return InventorySummary(
        on_hand=_num(r[7]),
        on_order=_num(r[8]),
        backorder=_num(r[9]),
        inventory_position=_num((r[7] or 0) + (r[8] or 0) - (r[9] or 0)),
        days_of_inventory=_num(r[4]),
        service_level_achieved=_num(r[0]),
        fill_rate=_num(r[1]),
        stockout_units=_num(r[2]),
        excess_inventory=_num(r[3]),
        safety_stock=_num(r[5]),
        reorder_point=_num(r[6]),
        horizon_days=horizon_days,
        provenance=Provenance.SIMULATED,
    )


def horizon(cur, series_token: str) -> InventoryHorizon:
    """Per-day position/on-hand/on-order/stockout for one series (28 bounded rows)."""
    key = parse_series(cur, series_token)
    if key is None:
        return InventoryHorizon(total=0)
    cur.execute(
        """
        SELECT day_id, inventory_position, on_hand, orders_placed,
               projected_stockout, stockout_units, days_of_inventory, data_provenance
        FROM fact_inventory_simulation
        WHERE product_surr_id = %s AND store_surr_id = %s
        ORDER BY day_id
        """,
        (key.product_surr_id, key.store_surr_id),
    )
    days = [
        InventoryDay(
            series=key,
            day_id=r[0],
            inventory_position=_num(r[1]),
            on_hand=_num(r[2]),
            on_order=_num(r[3]),
            stockout=bool(r[4]),
            stockout_units=_num(r[5]),
            days_of_inventory=_num(r[6]),
            provenance=Provenance(r[7]) if r[7] else Provenance.SIMULATED,
        )
        for r in cur.fetchall()
    ]
    return InventoryHorizon(series=key, days=days, total=len(days))


def policy(cur) -> InventoryPolicy:
    """Static policy snapshot from the baseline assumption set."""
    cur.execute(
        """
        SELECT assumption_set_id, name, safety_stock_formula, reorder_policy,
               reorder_quantity_rule, supplier_lead_time_days, service_level,
               starting_inventory_rule
        FROM assumption_set
        WHERE is_active = TRUE
        ORDER BY assumption_set_id
        LIMIT 1
        """
    )
    r = cur.fetchone()
    if r is None:
        return InventoryPolicy(provenance=Provenance.SIMULATED)
    return InventoryPolicy(
        assumption_set_id=r[0],
        policy_name=r[1],
        safety_stock_formula=r[2],
        reorder_policy=r[3],
        reorder_quantity_rule=r[4],
        supplier_lead_time_days=_num(r[5]),
        service_level_target=_num(r[6]),
        starting_inventory_rule=r[7],
        provenance=Provenance.SIMULATED,
    )


def _num(x):
    return float(x) if x is not None else None