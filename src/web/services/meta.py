"""Phase 6 metadata service — provenance/limitation/empty-state document.

Provides the locked metadata that the application shell exposes to the user:
the provenance contract (derived vs simulated), the documented limitations
(64-series ETS/SARIMA pilot, empty comparison table, no fact_daily_sales reads),
the reconciliation anchors, and the scenario run → definition map.
"""

import psycopg2.extras

from ..contracts.dashboard import MetaDoc
from .db import _scalar


def scenario_run_map(cur) -> list[dict]:
    cur.execute(
        """
        SELECT r.scenario_run_id, r.scenario_id, s.scenario_name, s.scenario_type,
               r.assumption_set_id, r.status, r.records_processed
        FROM fact_scenario_run r
        JOIN scenario s ON s.scenario_id = r.scenario_id
        ORDER BY r.scenario_run_id
        """
    )
    columns = [d[0] for d in cur.description or []]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def comparison_rows(cur) -> int:
    return _scalar(cur, "SELECT COUNT(*) FROM fact_scenario_comparison")


def _provenance_contract_text() -> dict[str, str]:
    # Mirrors docs/phase5_traceability.md section F (verified).
    return {
        "fact_forecast": "derived",
        "fact_forecast_evaluation": "derived",
        "fact_demand_analysis": "derived",
        "fact_product_store_demand": "derived",
        "fact_demand_seasonality": "derived",
        "fact_demand_seasonality_dow": "derived",
        "fact_inventory_simulation": "simulated",
        "fact_scenario_result": "simulated",
        "fact_scenario_run": "simulated",
        "scenario": "simulated",
        "fact_daily_sales": "observed (never read by the web layer)",
    }


def build_meta(cur) -> MetaDoc:
    comparison = comparison_rows(cur)
    return MetaDoc(
        provenance_contract=_provenance_contract_text(),
        limitations=[
            "ETS/SARIMA models (model ids 5–6) were evaluated on the 64-series pilot only; "
            "cross-model accuracy is only valid on the common pilot, not on all 30,490 series.",
            "Inventory and scenario figures are simulated under a documented assumption set; "
            "they are never presented as observed inventory.",
            "The web layer never reads fact_daily_sales directly; it consumes aggregated/derived "
            "surfaces only.",
        ],
        empty_states=[
            "fact_scenario_comparison has 0 rows (no action_tradeoff scenario); the scenario "
            "comparison view shows an explicit empty state rather than fabricated tradeoffs.",
            "Undefined metrics display literal '—' (never a fabricated zero).",
        ],
        reconcile_anchors={
            "observed_units": None,  # filled from DB by caller
            "forecast_final_grain": None,
            "inventory_grain": None,
            "scenario_result_rows": None,
            "evaluation_rows": None,
            "comparison_rows": comparison,
        },
        scenario_run_map=scenario_run_map(cur),
    )


def dimensions(cur) -> dict[str, list[str]]:
    """Bounded filter-dimension options (tiny lookup dims only)."""
    out: dict[str, list[str]] = {}
    cur.execute("SELECT dept_name FROM dim_department ORDER BY dept_name")
    out["departments"] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT category_name FROM dim_category ORDER BY category_name")
    out["categories"] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT store_id FROM dim_store ORDER BY store_id")
    out["stores"] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT state_id FROM dim_store ORDER BY state_id")
    out["states"] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT region_id FROM dim_store ORDER BY region_id")
    out["regions"] = [r[0] for r in cur.fetchall()]
    return out