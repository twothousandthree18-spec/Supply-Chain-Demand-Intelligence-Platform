"""Phase 6 risk / operational-insights data-access service.

Ranked series from the two locked rank runs in `fact_scenario_result`
(scenario_run 6 = stockout_risk_rank, 7 = excess_risk_rank). Each run carries a
unique risk_rank (1..30,490). Endpoints are server-side filtered (tier, product,
store) and paginated. risk_components (jsonb) provides the evidence breakdown.
All simulated.
"""

from ..contracts.common import Provenance
from ..contracts.dashboard import (
    RiskDrivers,
    RiskRank,
    RiskRankings,
)
from .db import parse_series

RISK_RUN = {"stockout": 6, "excess": 7}
RISK_TYPES = tuple(RISK_RUN.keys())
DEFAULT_RANK_TIERS = ("High", "Critical")
ALLOWED_TIERS = ("Low", "Medium", "High", "Critical")

# Keys presented to clients in a stable order (locked evidence schema).
_EVIDENCE_KEYS = ("urgency", "service_gap", "volume_rank",
                  "stockout_prob", "volatility_rank", "dominant")


def _run_id(risk_type: str) -> int:
    if risk_type not in RISK_RUN:
        raise ValueError(
            f"risk_type must be one of {', '.join(RISK_TYPES)}; got {risk_type!r}"
        )
    return RISK_RUN[risk_type]


def _filter_clause(filters):
    """Return (conditions_sql, params) for allowed filters (no WHERE keyword).

    Safe: keys come from an explicit allowlist and values are bound parameters.
    Dimension drill-down uses correlated EXISTS on the small dim tables (no
    fan-out). The rankings SQL already joins dim_product p and dim_store st, so
    those aliases resolve here.
    """
    allowed = {
        "tier": "r.risk_tier = %s",
        "product": "p.product_id = %s",
        "store": "st.store_id = %s",
        "department": (
            "EXISTS (SELECT 1 FROM dim_department dd WHERE dd.dept_surr_id = p.dept_surr_id "
            "AND dd.dept_name = %s)"
        ),
        "category": (
            "EXISTS (SELECT 1 FROM dim_category c WHERE c.category_surr_id = p.category_surr_id "
            "AND c.category_name = %s)"
        ),
        "state": "st.state_id = %s",
        "region": "st.region_id = %s",
    }
    clauses, params = [], []
    for key, value in (filters or {}).items():
        if value is None:
            continue
        expr = allowed.get(key)
        if expr:
            clauses.append(expr)
            params.append(value)
    return " AND ".join(clauses), params


def rankings(cur, *, risk_type, filters=None, page=1, page_size=25) -> RiskRankings:
    """Paginated, filtered stockout/excess risk ranking for a rank run."""
    run = _run_id(risk_type)
    cond, params = _filter_clause(filters)
    full_cond = " AND ".join(x for x in ("r.scenario_run_id = %s", cond) if x)
    where_sql = (" WHERE " + full_cond) if full_cond else ""
    count_params = (run,) + tuple(params)
    data_params = count_params + (page_size, (page - 1) * page_size)

    cur.execute(
        "SELECT COUNT(*) FROM fact_scenario_result r "
        "LEFT JOIN dim_product p ON p.product_surr_id = r.product_surr_id "
        "LEFT JOIN dim_store st ON st.store_surr_id = r.store_surr_id "
        + where_sql,
        count_params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        "SELECT p.product_id, st.store_id, r.risk_rank, r.risk_score, r.risk_tier,"
        "       coalesce((r.risk_components ->> 'dominant'), '') AS driver,"
        "       r.risk_components, r.data_provenance,"
        "       COALESCE(dd.dept_name, ''), COALESCE(c.category_name, ''),"
        "       COALESCE(st.state_id, ''), COALESCE(st.region_id, '')"
        " FROM fact_scenario_result r"
        " LEFT JOIN dim_product p ON p.product_surr_id = r.product_surr_id"
        " LEFT JOIN dim_store st ON st.store_surr_id = r.store_surr_id"
        " LEFT JOIN dim_department dd ON dd.dept_surr_id = p.dept_surr_id"
        " LEFT JOIN dim_category c ON c.category_surr_id = p.category_surr_id"
        + where_sql +
        " ORDER BY r.risk_rank"
        " LIMIT %s OFFSET %s",
        data_params,
    )

    items = [
        RiskRank(
            product=r[0],
            store=r[1],
            risk_rank=r[2],
            risk_score=_num(r[3]),
            risk_tier=r[4],
            primary_driver=r[5].strip(" \"") or None,
            evidence=_evidence(r[6]),
            provenance=Provenance(r[7]) if r[7] else Provenance.SIMULATED,
            department=r[8],
            category=r[9],
            state=r[10],
            region=r[11],
        )
        for r in cur.fetchall()
    ]
    from ..contracts.common import Pagination

    return RiskRankings(
        risk_type=risk_type,
        tier=filters.get("tier") if filters else None,
        pagination=Pagination(page=page, page_size=page_size, total=total),
        items=items,
    )


def drivers(cur, series_token: str) -> RiskDrivers:
    """risk_components + rank/score/tier for one series (baseline rank run)."""
    key = parse_series(cur, series_token)
    if key is None:
        return RiskDrivers()
    cur.execute(
        """
        SELECT risk_rank, risk_score, risk_tier, risk_components
        FROM fact_scenario_result
        WHERE scenario_run_id = %s AND product_surr_id = %s AND store_surr_id = %s
        """,
        (RISK_RUN["stockout"], key.product_surr_id, key.store_surr_id),
    )
    r = cur.fetchone()
    if r is None:
        return RiskDrivers(series=key, provenance=Provenance.SIMULATED)
    return RiskDrivers(
        series=key,
        risk_rank=r[0],
        risk_score=_num(r[1]),
        risk_tier=r[2],
        components=_evidence(r[3]),
        provenance=Provenance.SIMULATED,
    )


def _evidence(components):
    if not components:
        return {}
    out = {}
    for k in _EVIDENCE_KEYS:
        if k in components and components[k] is not None:
            out[k] = components[k]
    return out


def _num(x):
    return float(x) if x is not None else None