"""Phase 6 data-access database dependency (read-only connection lifecycle).

Reuses the project connection helper (src/etl/db_utils.connect) so the web
layer shares the same 12-factor semantics as every other phase. All endpoints
are query-only; nothing here writes.
"""

from typing import Iterator

from ..contracts.common import ProvenanceContract
from ..contracts.dashboard import DatabaseKey
from ..settings import Settings
from src.etl.db_utils import connect


def get_db(settings: Settings):
    """Yield a read-only psycopg2 cursor for a request scope."""
    conn = connect(autocommit=True)
    try:
        cur = conn.cursor()
        yield cur
        cur.close()
    finally:
        conn.close()


def _scalar(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def product_store_key(cur, product_surr_id, store_surr_id) -> DatabaseKey:
    """Resolve a product × store series to its surrogate + human-id key."""
    cur.execute(
        "SELECT p.product_id, st.store_id "
        "FROM dim_product p, dim_store st "
        "WHERE p.product_surr_id = %s AND st.store_surr_id = %s",
        (product_surr_id, store_surr_id),
    )
    row = cur.fetchone()
    return DatabaseKey(
        product_surr_id=product_surr_id,
        store_surr_id=store_surr_id,
        product=row[0] if row else None,
        store=row[1] if row else None,
    )


def parse_series(cur, series: str) -> DatabaseKey | None:
    """Parse a 'product:store' series token into surrogate ids via dim codes.

    Returns None when malformed or unmatched (caller returns an empty state).
    Accepts either human ids ('FOOD_00001:CA_1') or numeric surrogates.
    """
    if not series or ":" not in series:
        return None
    a, b = series.split(":", 1)
    a, b = a.strip(), b.strip()
    if a.isdigit() and b.isdigit():
        return _validate_key(cur, int(a), int(b))
    cur.execute(
        "SELECT p.product_surr_id, st.store_surr_id "
        "FROM dim_product p, dim_store st "
        "WHERE p.product_id = %s AND st.store_id = %s",
        (a, b),
    )
    row = cur.fetchone()
    return _validate_key(cur, row[0], row[1]) if row else None


def _validate_key(cur, product_surr_id, store_surr_id) -> DatabaseKey | None:
    cur.execute(
        "SELECT p.product_id, st.store_id "
        "FROM dim_product p, dim_store st "
        "WHERE p.product_surr_id = %s AND st.store_surr_id = %s",
        (product_surr_id, store_surr_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    return DatabaseKey(
        product_surr_id=product_surr_id,
        store_surr_id=store_surr_id,
        product=row[0],
        store=row[1],
    )


def page_meta(page, page_size, total) -> "object":
    from ..contracts.common import Pagination

    return Pagination(page=page, page_size=page_size, total=total)


def provenance_contract(cur) -> ProvenanceContract:
    """Small, aggregate-only cursor facts used by /api/health and /api/meta.

    These are the same locked reconciliation anchors from Phase 5 Step 1 tests.
    """
    return ProvenanceContract(
        observed_units=_scalar(cur, "SELECT SUM(units) FROM mv_weekly_sales"),
        forecast_final_grain=_scalar(
            cur, "SELECT COUNT(*) FROM fact_forecast WHERE is_final = TRUE"
        ),
        inventory_grain=_scalar(cur, "SELECT COUNT(*) FROM fact_inventory_simulation"),
        scenario_result_rows=_scalar(cur, "SELECT COUNT(*) FROM fact_scenario_result"),
        evaluation_rows=_scalar(cur, "SELECT COUNT(*) FROM fact_forecast_evaluation"),
        selected_model=_scalar(
            cur,
            "SELECT model_name FROM model_registry WHERE is_selected = TRUE ORDER BY model_id LIMIT 1",
        ),
        ets_sarima_pilot_series=_scalar(
            cur,
            "SELECT COUNT(*) FROM (SELECT DISTINCT product_surr_id, store_surr_id "
            "FROM fact_forecast_evaluation WHERE model_id IN (5, 6)) AS pilot",
        ),
    )