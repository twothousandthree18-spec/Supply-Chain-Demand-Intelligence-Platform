"""Phase 6 forecast data-access service.

Reads `model_registry` (6 models) and `fact_forecast_evaluation` (bounded
accuracy aggregates, 30,490 support for models 1–4 and the 64-series pilot for
ETS/SARIMA 5–6) and the bounded 28-day `fact_forecast` horizon for one series.
Forecast math is never recomputed here — stored MAE/RMSE/WMAE/WRMSE values and
model metadata are returned as-is, and the 64-series ETS/SARIMA support
limitation is surfaced explicitly.
"""

from ..contracts.common import Provenance
from ..contracts.dashboard import (
    ForecastAccuracy,
    ForecastAccuracyRow,
    ForecastModel,
    ForecastModels,
    ForecastPoint,
    ForecastSeries,
)
from .db import parse_series

PILOT_MODEL_IDS = (5, 6)  # ets_holt_winters, sarima — evaluated on the 64-series pilot


def models(cur) -> ForecastModels:
    """Model registry + per-model evaluation support + pilot caveat."""
    cur.execute(
        """
        SELECT m.model_id, m.model_name, m.model_family, m.is_selected,
               m.validation_start, m.validation_end, m.selection_rationale,
               m.metrics_json,
               (SELECT COUNT(DISTINCT e.product_surr_id || ':' || e.store_surr_id)
                  FROM fact_forecast_evaluation e WHERE e.model_id = m.model_id) AS support
        FROM model_registry m
        ORDER BY m.model_id
        """
    )
    out = []
    for r in cur.fetchall():
        metrics = _metrics_from_json(r[7])
        out.append(
            ForecastModel(
                model_id=r[0],
                model_name=r[1],
                model_family=r[2],
                is_selected=bool(r[3]),
                validation_start=r[4],
                validation_end=r[5],
                selection_rationale=r[6],
                metrics=metrics,
                support_series=int(r[8]),
                pilot_limited=r[0] in PILOT_MODEL_IDS,
            )
        )
    selected = next((m for m in out if m.is_selected), None)
    return ForecastModels(
        models=out,
        model_count=len(out),
        pilot_series=_pilot_series(cur),
        limitation_note=(
            "ETS/SARIMA models 5–6 were evaluated on the 64-series pilot only; "
            "cross-model comparison is valid on the common pilot, not all 30,490 series."
        ),
    )


def accuracy(cur) -> ForecastAccuracy:
    """Per-model accuracy with support counts and the pilot caveat preserved."""
    cur.execute(
        """
        SELECT e.model_id, m.model_name,
               (SELECT COUNT(DISTINCT e2.product_surr_id || ':' || e2.store_surr_id)
                  FROM fact_forecast_evaluation e2 WHERE e2.model_id = e.model_id) AS support,
               AVG(e.mae), AVG(e.rmse), AVG(e.wmae), AVG(e.wrmse),
               AVG(e.abs_error), AVG(e.bias)
        FROM fact_forecast_evaluation e
        JOIN model_registry m ON m.model_id = e.model_id
        GROUP BY e.model_id, m.model_name
        ORDER BY e.model_id
        """
    )
    rows = []
    for r in cur.fetchall():
        support = int(r[2])
        pilot_limited = r[0] in PILOT_MODEL_IDS
        rows.append(
            ForecastAccuracyRow(
                model_id=r[0],
                model_name=r[1],
                support_series=support,
                mae=_num(r[3]),
                rmse=_num(r[4]),
                wmae=_num(r[5]),
                wrmse=_num(r[6]),
                abs_error=_num(r[7]),
                bias=_num(r[8]),
                undefined=r[3] is None,
                pilot_limited=pilot_limited,
            )
        )
    selected = _selected_model(cur)
    return ForecastAccuracy(
        rows=rows,
        selected_model=selected,
        pilot_series=_pilot_series(cur),
        caveat=(
            "ETS/SARIMA (models 5–6) support is limited to the 64-series pilot; "
            "their accuracy figures are not directly comparable to the 30,490-series "
            "models 1–4 without re-scoring on the common denominator."
        ) if any(r.pilot_limited for r in rows) else None,
    )


def series(cur, series_token: str) -> ForecastSeries:
    """One series' 28-day final forecast (1:1 bounded, no fan-out).

    Returns an empty result when the series token is unknown.
    """
    key = parse_series(cur, series_token)
    if key is None:
        return ForecastSeries(total=0)
    cur.execute(
        """
        SELECT forecast_date, forecast_value, lower_bound, upper_bound,
               forecast_origin, forecast_horizon, data_provenance
        FROM fact_forecast
        WHERE product_surr_id = %s AND store_surr_id = %s AND is_final = TRUE
        ORDER BY forecast_date
        """,
        (key.product_surr_id, key.store_surr_id),
    )
    points = [
        ForecastPoint(
            series=key,
            forecast_date=r[0],
            forecast_value=_num(r[1]),
            lower_bound=_num(r[2]),
            upper_bound=_num(r[3]),
            origin=r[4],
            horizon=r[5],
            provenance=Provenance(r[6]) if r[6] else Provenance.DERIVED,
        )
        for r in cur.fetchall()
    ]
    return ForecastSeries(series=key, points=points, total=len(points))


def _pilot_series(cur):
    cur.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT product_surr_id, store_surr_id "
        "FROM fact_forecast_evaluation WHERE model_id IN (5, 6)) AS pilot"
    )
    return cur.fetchone()[0]


def _selected_model(cur):
    cur.execute(
        "SELECT model_name FROM model_registry WHERE is_selected = TRUE "
        "ORDER BY model_id LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def _metrics_from_json(metrics_json):
    if not metrics_json:
        return {}
    try:
        return {k: (_num(v) if isinstance(v, (int, float)) else v) for k, v in metrics_json.items()}
    except Exception:
        return {}


def _num(x):
    return float(x) if x is not None else None