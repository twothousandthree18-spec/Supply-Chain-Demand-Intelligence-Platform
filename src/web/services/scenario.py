"""Phase 6 scenario data-access service.

Reads `fact_scenario_run` × `scenario` (run → metadata/status) and the
`fact_scenario_result` delta_* columns (per-scenario vs baseline, simulated).
`fact_scenario_comparison` is empty (0 rows) in the locked production set and is
surfaced as an explicit empty state rather than fabricated tradeoffs.
"""

from ..contracts.common import Provenance
from ..contracts.dashboard import (
    ComparisonStatus,
    ScenarioDelta,
    ScenarioDeltas,
    ScenarioRunStatus,
    ScenarioRuns,
)


def runs(cur) -> ScenarioRuns:
    """Run id → name/type/assumption/status/records_processed (7 runs)."""
    cur.execute(
        """
        SELECT r.scenario_run_id, r.scenario_id, s.scenario_name, s.scenario_type,
               r.assumption_set_id, r.status, r.records_processed, r.executed_at,
               r.data_provenance
        FROM fact_scenario_run r
        JOIN scenario s ON s.scenario_id = r.scenario_id
        ORDER BY r.scenario_run_id
        """
    )
    out = []
    for r in cur.fetchall():
        out.append(
            ScenarioRunStatus(
                scenario_run_id=r[0],
                scenario_id=r[1],
                scenario_name=r[2],
                scenario_type=r[3],
                assumption_set_id=r[4],
                status=r[5],
                records_processed=int(r[6]) if r[6] is not None else None,
                executed_at=r[7].isoformat() if r[7] else None,
                provenance=Provenance(r[8]) if r[8] else Provenance.SIMULATED,
            )
        )
    return ScenarioRuns(runs=out, total=len(out))


def deltas(cur) -> ScenarioDeltas:
    """Per-scenario vs-baseline delta aggregates over the 213K result table.

    Aggregated per scenario_run_id (excluding the baseline run itself) over the
    bounded fact_scenario_result. All simulated.
    """
    base = _baseline_run(cur)
    cur.execute(
        """
        SELECT r.scenario_run_id, rr.scenario_id, s.scenario_name, s.scenario_type,
               AVG(r.delta_stockout_days)::float8,
               AVG(r.delta_service_level)::float8,
               AVG(r.delta_fill_rate)::float8,
               AVG(r.delta_reorder_frequency)::float8,
               AVG(r.delta_avg_inventory_position)::float8,
               AVG(r.delta_excess_days)::float8,
               AVG(r.delta_avg_days_of_inventory)::float8,
               COUNT(*) AS n
        FROM fact_scenario_result r
        JOIN fact_scenario_run rr ON rr.scenario_run_id = r.scenario_run_id
        JOIN scenario s ON s.scenario_id = rr.scenario_id
        WHERE r.scenario_run_id <> %s
        GROUP BY r.scenario_run_id, rr.scenario_id, s.scenario_name, s.scenario_type
        ORDER BY r.scenario_run_id
        """,
        (base,),
    )
    out = []
    for r in cur.fetchall():
        out.append(
            ScenarioDelta(
                scenario_run_id=r[0],
                scenario_id=r[1],
                name=r[2],
                scenario_type=r[3],
                delta_stockout_days=_num(r[4]),
                delta_service_level=_num(r[5]),
                delta_fill_rate=_num(r[6]),
                delta_reorder_frequency=_num(r[7]),
                delta_avg_inventory_position=_num(r[8]),
                delta_excess_days=_num(r[9]),
                delta_avg_days_of_inventory=_num(r[10]),
                series_count=int(r[11]),
                provenance=Provenance.SIMULATED,
            )
        )
    return ScenarioDeltas(deltas=out, total=len(out))


def comparison(cur) -> ComparisonStatus:
    """Explicit empty-state for fact_scenario_comparison (0 rows)."""
    cur.execute("SELECT COUNT(*) FROM fact_scenario_comparison")
    rows = cur.fetchone()[0]
    return ComparisonStatus(
        present=rows > 0,
        rows=int(rows),
        reason=(
            "comparison tradeoffs available" if rows > 0
            else "no action_tradeoff scenario in the production set (0 comparison rows)"
        ),
    )


def _baseline_run(cur) -> int | None:
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
    return row[0] if row else -1


def _num(x):
    return float(x) if x is not None else None