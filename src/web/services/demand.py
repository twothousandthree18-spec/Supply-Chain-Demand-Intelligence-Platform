"""Phase 6 demand data-access service.

Reads the bounded `fact_demand_analysis` (30,490 series, one row per product ×
store, `observed_full` window), `fact_demand_seasonality` (per-series monthly
indices), and `fact_demand_seasonality_dow` (scope DOW profiles). All outputs
are derived, server-side filtered/paginated, and bounded — nothing scans
`fact_daily_sales`. No demand math is recomputed here; only stored aggregates
are selected.
"""

from ..contracts.common import Provenance
from ..contracts.dashboard import (
    DemandDow,
    DemandRow,
    DemandSegments,
    DemandSeasonality,
    DowPoint,
    SeasonalMonth,
)
from .db import product_store_key

_SEGMENT_FIELDS = ("segment_volume", "segment_volatility", "segment_demand",
                   "risk_cell", "risk_category", "trend_direction")


def _filter_clause(filters):
    """Build (where_sql, params) for allowed scalar equality filters.

    Safe: keys come from an explicit allowlist, values are passed as bound
    parameters (never string-interpolated). where_sql has a leading space.
    """
    allowed = {
        "risk_category": "risk_category = %s",
        "volatility_class": "segment_volatility = %s",
        "volume_class": "segment_volume = %s",
        "trend_direction": "trend_direction = %s",
        "product": "p.product_id = %s",
        "store": "st.store_id = %s",
        "window": "analysis_window = %s",
        # Dimension drill-down via correlated subqueries (no fan-out) — the demand
        # SQL joins dim_product p and dim_store st, so references resolve here.
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
        if not expr:
            continue
        clauses.append(expr)
        params.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def demand_rows(cur, *, filters=None, page=1, page_size=25, sort=None):
    """Paginated, server-side-filtered demand-analysis list."""
    where, params = _filter_clause(filters)
    order_by, _order_params = _order_clause(sort)

    count_sql = (
        "SELECT COUNT(*) FROM fact_demand_analysis d "
        "LEFT JOIN dim_product p ON p.product_surr_id = d.product_surr_id "
        "LEFT JOIN dim_store st ON st.store_surr_id = d.store_surr_id "
        + where
    )
    cur.execute(count_sql, params)
    total = cur.fetchone()[0]

    sql = (
        "SELECT d.analysis_window, p.product_id, st.store_id,"
        "       d.mean_daily_units, d.cv, d.segment_volatility,"
        "       d.demand_growth_rate, d.growth_is_defined, d.trend_direction,"
        "       d.trend_effect_pct, d.seasonality_strength, d.peak_month,"
        "       d.trough_month, d.segment_volume, d.segment_volatility,"
        "       d.segment_demand, d.risk_cell, d.risk_category, d.data_provenance"
        " FROM fact_demand_analysis d"
        " LEFT JOIN dim_product p ON p.product_surr_id = d.product_surr_id"
        " LEFT JOIN dim_store st ON st.store_surr_id = d.store_surr_id"
        + where
        + " ORDER BY " + order_by
        + " LIMIT %s OFFSET %s"
    )
    cur.execute(sql, params + [page_size, (page - 1) * page_size])

    rows = []
    for r in cur.fetchall():
        rows.append(
            DemandRow(
                product=r[1],
                store=r[2],
                mean_daily_units=_num(r[3]),
                cv=_num(r[4]),
                volatility_class=r[5],
                demand_growth_rate=_num(r[6]),
                growth_defined=bool(r[7]),
                trend_direction=r[8],
                trend_effect_pct=_num(r[9]),
                seasonality_strength=_num(r[10]),
                peak_month=r[11],
                trough_month=r[12],
                segment_volume=r[13],
                segment_volatility=r[14],
                segment_demand=r[15],
                risk_cell=r[16],
                risk_category=r[17],
                provenance=Provenance(r[18]) if r[18] else Provenance.DERIVED,
            )
        )
    from ..contracts.common import Page, Pagination

    return Page[DemandRow](
        pagination=Pagination(page=page, page_size=page_size, total=total),
        items=rows,
    )


def _order_clause(sort):
    """Map a sort token to a bounded ORDER BY; default by product then store."""
    if sort in ("product", "product_id"):
        return "p.product_id ASC, st.store_id ASC", []
    if sort in ("mean_daily_units", "mean_daily_units_asc"):
        return "d.mean_daily_units ASC", []
    if sort == "cv":
        return "d.cv ASC", []
    if sort == "cv_desc":
        return "d.cv DESC", []
    if sort == "risk":
        return "d.risk_category DESC, d.segment_volatility DESC", []
    return "p.product_id ASC, st.store_id ASC", []


def demand_segments(cur, *, filters=None):
    """Volume × volatility matrix and risk-category breaks over bounded demand."""
    where, params = _filter_clause(filters)

    matrix_sql = (
        "SELECT d.segment_volume, d.segment_volatility, COUNT(*) AS n"
        " FROM fact_demand_analysis d"
        " LEFT JOIN dim_product p ON p.product_surr_id = d.product_surr_id"
        " LEFT JOIN dim_store st ON st.store_surr_id = d.store_surr_id"
        + where +
        " GROUP BY d.segment_volume, d.segment_volatility"
        " ORDER BY d.segment_volume, d.segment_volatility"
    )
    cur.execute(matrix_sql, params)
    matrix = [
        {"volume": r[0], "volatility": r[1], "count": int(r[2])}
        for r in cur.fetchall()
    ]

    breaks_sql = (
        "SELECT d.risk_category, COUNT(*) AS n"
        " FROM fact_demand_analysis d"
        " LEFT JOIN dim_product p ON p.product_surr_id = d.product_surr_id"
        " LEFT JOIN dim_store st ON st.store_surr_id = d.store_surr_id"
        + where +
        " GROUP BY d.risk_category"
        " ORDER BY d.risk_category"
    )
    cur.execute(breaks_sql, params)
    breaks = [
        {"risk_category": r[0], "count": int(r[1])}
        for r in cur.fetchall()
    ]
    return DemandSegments(
        volume_classes=sorted({r["volume"] for r in matrix if r["volume"]}),
        volatility_classes=sorted({r["volatility"] for r in matrix if r["volatility"]}),
        matrix=matrix,
        risk_breaks=breaks,
    )


def demand_seasonality(cur, product_surr_id, store_surr_id):
    """Per-series monthly seasonal indices + strength/peak/trough (bounded)."""
    cur.execute(
        """
        SELECT a.seasonality_strength, a.has_meaningful_seasonality,
               a.peak_month, a.trough_month, a.analysis_window
        FROM fact_demand_analysis a
        WHERE a.product_surr_id = %s AND a.store_surr_id = %s
        """,
        (product_surr_id, store_surr_id),
    )
    agg = cur.fetchone()
    cur.execute(
        """
        SELECT s.month, s.seasonality_index, s.obs_weeks
        FROM fact_demand_seasonality s
        WHERE s.product_surr_id = %s AND s.store_surr_id = %s
        ORDER BY s.month
        """,
        (product_surr_id, store_surr_id),
    )
    indices = [
        SeasonalMonth(month=r[0], seasonal_index=_num(r[1]), obs_weeks=int(r[2]))
        for r in cur.fetchall()
    ]
    if indices:
        a = agg or (None, None, None, None, "observed_full")
        strength = a[0] if a else None
    else:
        strength = agg[0] if (agg and agg[0] is not None) else None
    has = bool(agg[1]) if agg else bool(indices)
    return DemandSeasonality(
        series=product_store_key(cur, product_surr_id, store_surr_id),
        strength=_num(strength),
        has_meaningful_seasonality=has,
        peak_month=agg[2] if agg else None,
        trough_month=agg[3] if agg else None,
        monthly_indices=indices,
    )


def demand_dow(cur, scope_type=None):
    """DOW profile indices per scope (all, category, dept, state, store)."""
    if scope_type:
        cur.execute(
            """
            SELECT scope_type, scope_key, scope_value, weekday_num, weekday_name,
                   dow_index, obs_days, data_provenance
            FROM fact_demand_seasonality_dow
            WHERE scope_type = %s
            ORDER BY scope_key NULLS FIRST, weekday_num
            """,
            (scope_type,),
        )
        points = [_dow_point(r) for r in cur.fetchall()]
        return DemandDow(scope_type=scope_type, points=points)
    cur.execute(
        """
        SELECT scope_type, scope_key, scope_value, weekday_num, weekday_name,
               dow_index, obs_days, data_provenance
        FROM fact_demand_seasonality_dow
        ORDER BY scope_type, scope_key NULLS FIRST, weekday_num
        """
    )
    grouped: dict[str, list[DowPoint]] = {}
    for r in cur.fetchall():
        grouped.setdefault(r[0], []).append(_dow_point(r))
    return DemandDow(scope_type=scope_type or "all", points=grouped.get("all", []))


def _dow_point(r):
    return DowPoint(
        scope_type=r[0],
        scope_key=r[1],
        scope_value=r[2],
        weekday_num=r[3],
        weekday_name=r[4],
        dow_index=_num(r[5]),
        obs_days=int(r[6]),
        provenance=Provenance(r[7]) if r[7] else Provenance.DERIVED,
    )


def _num(x):
    return float(x) if x is not None else None