"""Phase 6 executive data-access service.

Reads only the small materialized v_* rollups (weekly revenue/units/price/growth
and contribution views). All outputs are derived and bounded; nothing touches
fact_daily_sales. Returns typed contracts (contracts/dashboard.py).
"""

from ..contracts.common import MetricValue, Provenance
from ..contracts.dashboard import (
    ContributionRow,
    ExecutiveContributions,
    ExecutiveSnapshot,
    OperationalSignal,
    SignalSummary,
    TrendPoint,
)


def headline_snapshot(cur) -> ExecutiveSnapshot:
    """Headline KPIs + bounded revenue trend in one ~2s pass over mv_weekly_sales.

    The dedicated v_revenue / v_growth_* rollup views recompute heavyweight GROUP
    BY / window aggregates over the 8.4M-row base on every call (v_growth_wow alone
    is ~50s), which is not suitable for an interactive shell. This reads the locked
    materialized mv_weekly_sales (+ dim_date for calendar) directly in a single
    weekly GROUP BY pass and derives the growth percentages in-process.

    Definitions (documented, period-over-period on the latest week):
      - WoW  = (latest_week − prior_week) / prior_week ×100
      - QoQ  = (quarter_of_latest_week − previous_quarter) / previous_quarter ×100
      - YoY  = (year_of_latest_week − previous_year) / previous_year ×100
    Undefined (missing denominator) renders as MetricValue.blank() -> "—".
    Nothing is scanned at daily grain.
    """
    cur.execute(
        """
        WITH week_cal AS (
            SELECT wm_yr_wk, MIN(year) AS year, MIN(quarter) AS quarter
            FROM dim_date
            GROUP BY wm_yr_wk
        ),
        weekly AS (
            SELECT s.wm_yr_wk,
                   SUM(s.units)   AS units,
                   SUM(s.revenue) AS revenue,
                   c.year,
                   c.quarter
            FROM mv_weekly_sales s
            LEFT JOIN week_cal c USING (wm_yr_wk)
            GROUP BY s.wm_yr_wk, c.year, c.quarter
        )
        SELECT wm_yr_wk, units, revenue, year, quarter
        FROM weekly
        ORDER BY wm_yr_wk
        """
    )
    weekly_all = cur.fetchall()  # rows: (wm_yr_wk, units, revenue, year, quarter)

    units_tot = round(sum(r[1] for r in weekly_all))
    revenue_tot = round(sum(r[2] for r in weekly_all))

    trend = [
        TrendPoint(period=wm, units=units, revenue=revenue)
        for wm, units, revenue, _y, _q in weekly_all[-12:]
    ]

    headline = _build_headline(units_tot, revenue_tot, weekly_all)
    return ExecutiveSnapshot(headline=headline, revenue_trend=trend)


def _build_headline(units_tot, revenue_tot, weekly_all):
    from ..contracts.dashboard import HeadlineKpis

    # Latest vs prior week -> WoW.
    wow_rev = wow_units = None
    qoq = yoy_rev = yoy_units = None
    if len(weekly_all) >= 2:
        cur_wk, prior_wk = weekly_all[-1], weekly_all[-2]
        wow_units = _period_pct(cur_wk[1], prior_wk[1])
        wow_rev = _period_pct(cur_wk[2], prior_wk[2])

    latest_year = weekly_all[-1][3] if weekly_all else None
    latest_q = weekly_all[-1][4] if weekly_all else None

    # QoQ: latest quarter (of latest week) vs the immediately prior quarter present.
    q_series = {}
    for row in weekly_all:
        q_series.setdefault((row[3], row[4]), [0, 0])  # (year,q) -> [units, revenue]
        q_series[(row[3], row[4])][0] += row[1]
        q_series[(row[3], row[4])][1] += row[2]
    q_keys = sorted(q_series.keys())
    if latest_q is not None and len(q_keys) >= 2:
        cur_cell = q_series[(latest_year, latest_q)]
        prev_key = _prev_quarter(q_keys, (latest_year, latest_q))
        if prev_key is not None and q_series[prev_key][0]:
            qoq = _period_pct(cur_cell[1], q_series[prev_key][1])

    # YoY: latest year vs previous year present.
    y_series = {}
    for row in weekly_all:
        y_series.setdefault(row[3], [0, 0])
        y_series[row[3]][0] += row[1]
        y_series[row[3]][1] += row[2]
    y_keys = sorted(y_series.keys())
    if latest_year is not None and len(y_keys) >= 2 and y_keys[-2] in y_series:
        cur_c = y_series[latest_year]
        prev_c = y_series[y_keys[-2]]
        yoy_units = _period_pct(cur_c[0], prev_c[0])
        yoy_rev = _period_pct(cur_c[1], prev_c[1])

    return HeadlineKpis(
        revenue=MetricValue(value=_round(revenue_tot), unit="USD", provenance=Provenance.DERIVED),
        units=MetricValue(value=units_tot, unit="units", provenance=Provenance.DERIVED),
        weighted_price=_price(revenue_tot, units_tot),
        revenue_wow_pct=_pct(wow_rev),
        units_wow_pct=_pct(wow_units),
        revenue_qoq_pct=_pct(qoq),
        revenue_yoy_pct=_pct(yoy_rev),
        units_yoy_pct=_pct(yoy_units),
    )


def _period_pct(cur, prior):
    """(cur/prior − 1)×100, None when prior missing/zero (undefined)."""
    if cur is None or prior in (None, 0):
        return None
    return (cur - prior) / prior * 100


def _prev_quarter(keys, current):
    """Return the quarter key immediately before current in the sorted list, or None."""
    for i, k in enumerate(keys):
        if k == current and i > 0:
            return keys[i - 1]
    return None


def _price(revenue, units):
    if units in (None, 0):
        return MetricValue.blank(Provenance.DERIVED)
    return MetricValue(value=_round(revenue / units), unit="USD/unit", provenance=Provenance.DERIVED)


def _pct(val):
    if val is None:
        return MetricValue.blank(Provenance.DERIVED)
    return MetricValue(value=_round(val, 2), unit="%", provenance=Provenance.DERIVED)


def _round(x, nd=2):
    return round(float(x), nd) if x is not None else None


_FILTER_COLUMNS = {
    # filter key -> SQL expression referencing p (dim_product) or st (dim_store)
    # Column filters are applied as correlated subqueries so no cross-table fan-out
    # is introduced and every scan stays a bounded single pass.
    "department": (
        "EXISTS (SELECT 1 FROM dim_department dd WHERE dd.dept_surr_id = p.dept_surr_id "
        "AND dd.dept_name = %s)"
    ),
    "category": (
        "EXISTS (SELECT 1 FROM dim_category c WHERE c.category_surr_id = p.category_surr_id "
        "AND c.category_name = %s)"
    ),
    "product": "p.product_id = %s",
    "store": "st.store_id = %s",
    "state": "st.state_id = %s",
    "region": "st.region_id = %s",
}


def _filter_where(filters):
    """Build (sql, params) for allowable contribution filters (bounded)."""
    clauses, params = [], []
    for key, value in (filters or {}).items():
        if value in (None, ""):
            continue
        expr = _FILTER_COLUMNS.get(key)
        if expr:
            clauses.append(expr)
            params.append(value)
    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def contributions(cur, filters=None, top_n: int = 10) -> ExecutiveContributions:
    top_n = max(1, min(int(top_n or 10), 50))
    filter_sql, params = _filter_where(filters)
    total_revenue = 0.0
    # Grand revenue under the same filter (bounded), so shares stay consistent.
    cur.execute(
        "SELECT COALESCE(SUM(s.revenue), 0) FROM mv_weekly_sales s "
        "JOIN dim_product p ON p.product_surr_id = s.product_surr_id "
        "JOIN dim_store st ON st.store_surr_id = s.store_surr_id" + filter_sql,
        params,
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        total_revenue = float(row[0])
    return ExecutiveContributions(
        by_product=_rows_product(cur, total_revenue, filter_sql, params, top_n),
        by_department=_rows_department(cur, total_revenue, filter_sql, params, top_n),
        by_state=_rows_state(cur, total_revenue, filter_sql, params, top_n),
    )


def _rows_product(cur, total_revenue, filter_sql, params, top_n):
    # Direct GROUP BY over the locked mv_weekly_sales (fast pass) avoiding the
    # slower v_product_contribution view. share_pct relative to (filtered) revenue.
    cur.execute(
        """
        SELECT p.product_id, SUM(s.revenue) AS rev
        FROM mv_weekly_sales s
        JOIN dim_product p ON p.product_surr_id = s.product_surr_id
        JOIN dim_store st ON st.store_surr_id = s.store_surr_id
        """
        + filter_sql
        + " GROUP BY p.product_id ORDER BY rev DESC LIMIT %s",
        params + [top_n],
    )
    out = []
    for i, (pk, rev) in enumerate(cur.fetchall()):
        out.append(
            ContributionRow(
                entity=pk, value=rev, share_pct=_share(rev, total_revenue),
                rank=i + 1, provenance=Provenance.DERIVED,
            )
        )
    return out


def _rows_department(cur, total_revenue, filter_sql, params, top_n):
    cur.execute(
        """
        SELECT d.dept_name, SUM(s.revenue) AS rev
        FROM mv_weekly_sales s
        JOIN dim_product p ON p.product_surr_id = s.product_surr_id
        JOIN dim_store st ON st.store_surr_id = s.store_surr_id
        JOIN dim_department d ON d.dept_surr_id = p.dept_surr_id
        """
        + filter_sql
        + " GROUP BY d.dept_name ORDER BY rev DESC LIMIT %s",
        params + [top_n],
    )
    return [
        ContributionRow(
            entity=name, value=rev, share_pct=_share(rev, total_revenue),
            rank=i + 1, provenance=Provenance.DERIVED,
        )
        for i, (name, rev) in enumerate(cur.fetchall())
    ]


def _rows_state(cur, total_revenue, filter_sql, params, top_n):
    cur.execute(
        """
        SELECT st.state_id, SUM(s.revenue) AS rev
        FROM mv_weekly_sales s
        JOIN dim_product p ON p.product_surr_id = s.product_surr_id
        JOIN dim_store st ON st.store_surr_id = s.store_surr_id
        """
        + filter_sql
        + " GROUP BY st.state_id ORDER BY rev DESC LIMIT %s",
        params + [top_n],
    )
    return [
        ContributionRow(
            entity=state, value=rev, share_pct=_share(rev, total_revenue),
            rank=i + 1, provenance=Provenance.DERIVED,
        )
        for i, (state, rev) in enumerate(cur.fetchall())
    ]


def _share(rev, total_revenue):
    if total_revenue in (None, 0):
        return None
    return round(float(rev) / total_revenue * 100, 4)


def signals(cur) -> SignalSummary:
    """Top stockout/excess operational signals from the two rank runs (simulated)."""
    out = []
    for risk_type, run in (("stockout", 6), ("excess", 7)):
        cur.execute(
            """
            SELECT p.product_id, st.store_id, r.risk_tier, r.risk_score, r.risk_rank,
                   coalesce((r.risk_components -> 'dominant')::text, '') AS driver
            FROM fact_scenario_result r
            JOIN dim_product p ON p.product_surr_id = r.product_surr_id
            JOIN dim_store st ON st.store_surr_id = r.store_surr_id
            WHERE r.scenario_run_id = %s AND r.risk_tier IN ('High', 'Critical')
            ORDER BY r.risk_rank
            LIMIT 8
            """,
            (run,),
        )
        for pk, store, tier, score, rank, driver in cur.fetchall():
            out.append(
                OperationalSignal(
                    product=pk, store=store, risk_type=risk_type, tier=tier,
                    score=score, rank=rank,
                    primary_driver=driver.strip(" \"") or None,
                    provenance=Provenance.SIMULATED,
                )
            )
    return SignalSummary(stockout_at_risk=_count_tier(cur, 6), excess_at_risk=_count_tier(cur, 7), signals=out)


def _count_tier(cur, run):
    cur.execute(
        "SELECT COUNT(*) FROM fact_scenario_result "
        "WHERE scenario_run_id = %s AND risk_tier IN ('High', 'Critical')",
        (run,),
    )
    return cur.fetchone()[0]