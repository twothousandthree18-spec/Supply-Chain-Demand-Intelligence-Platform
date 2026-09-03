"""Phase 6 routers — dashboard product-area data endpoints.

Declares the full data-access surface (executive + demand + forecast + inventory
+ scenario + risk). Every endpoint is read-only and returns a typed pydantic
contract. Filters/ordering/pagination are enforced server-side so the browser
never receives an unbounded payload.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..contracts.common import Page
from ..contracts.dashboard import (
    ComparisonStatus,
    DemandDow,
    DemandRow,
    DemandSeasonality,
    DemandSegments,
    ExecutiveContributions,
    ExecutiveSnapshot,
    ForecastAccuracy,
    ForecastModels,
    ForecastSeries,
    InventoryHorizon,
    InventoryPolicy,
    InventorySummary,
    RiskDrivers,
    RiskRankings,
    ScenarioDeltas,
    ScenarioRuns,
    SignalSummary,
)
from ..services import (
    demand as demand_service,
    executive as executive_service,
    forecast as forecast_service,
    inventory as inventory_service,
    risk as risk_service,
    scenario as scenario_service,
)

router = APIRouter(tags=["dashboard"])

MAX_PAGE_SIZE = 200


def _get_db():
    from ..services.db import get_db
    from ..settings import get_settings

    yield from get_db(get_settings())


def _page(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE)):
    return page, page_size


# --- Executive ----------------------------------------------------------------- #
@router.get("/kpis/executive", response_model=ExecutiveSnapshot)
def executive_kpis(cur=Depends(_get_db)):
    """Headline revenue/units/price/growth KPIs + bounded revenue trend."""
    return executive_service.headline_snapshot(cur)


@router.get("/kpis/contributions", response_model=ExecutiveContributions)
def executive_contributions(
    cur=Depends(_get_db),
    department: str | None = Query(None),
    category: str | None = Query(None),
    product: str | None = Query(None),
    store: str | None = Query(None),
    state: str | None = Query(None),
    region: str | None = Query(None),
    top_n: int = Query(10, ge=1, le=50),
):
    """Revenue concentration (product / department / state share) with bounded
    server-side filters + Top-N. No fact_daily_sales; single-pass over weekly."""
    filters = {
        "department": department,
        "category": category,
        "product": product,
        "store": store,
        "state": state,
        "region": region,
    }
    return executive_service.contributions(cur, filters=filters, top_n=top_n)


@router.get("/executive/signals", response_model=SignalSummary)
def executive_signals(cur=Depends(_get_db)):
    """High-priority operational signals from stockout/excess rank runs (simulated)."""
    return executive_service.signals(cur)


# --- Demand -------------------------------------------------------------------- #
@router.get("/analytics/demand", response_model=Page[DemandRow])
def demand_rows(
    cur=Depends(_get_db),
    risk_category: str | None = Query(None),
    volatility_class: str | None = Query(None),
    volume_class: str | None = Query(None),
    trend_direction: str | None = Query(None),
    product: str | None = Query(None),
    store: str | None = Query(None),
    department: str | None = Query(None),
    category: str | None = Query(None),
    state: str | None = Query(None),
    region: str | None = Query(None),
    window: str | None = Query(None, pattern="^[A-Za-z0-9_]+$"),
    sort: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
):
    """Paginated, filtered demand-analysis series (server-side, dim drill-down)."""
    filters = {
        "risk_category": risk_category,
        "volatility_class": volatility_class,
        "volume_class": volume_class,
        "trend_direction": trend_direction,
        "product": product,
        "store": store,
        "department": department,
        "category": category,
        "state": state,
        "region": region,
        "window": window,
    }
    return demand_service.demand_rows(
        cur, filters=filters, page=page, page_size=page_size, sort=sort
    )


@router.get("/analytics/demand/segments", response_model=DemandSegments)
def demand_segments(
    cur=Depends(_get_db),
    risk_category: str | None = Query(None),
    volatility_class: str | None = Query(None),
    volume_class: str | None = Query(None),
    product: str | None = Query(None),
    store: str | None = Query(None),
    department: str | None = Query(None),
    category: str | None = Query(None),
    state: str | None = Query(None),
    region: str | None = Query(None),
):
    """Volume × volatility matrix + risk-category breaks (bounded, dim drill-down)."""
    filters = {
        "risk_category": risk_category,
        "volatility_class": volatility_class,
        "volume_class": volume_class,
        "product": product,
        "store": store,
        "department": department,
        "category": category,
        "state": state,
        "region": region,
    }
    return demand_service.demand_segments(cur, filters=filters)


@router.get("/analytics/demand/seasonality", response_model=DemandSeasonality)
def demand_seasonality(
    cur=Depends(_get_db),
    product_surr: int | None = Query(None),
    store_surr: int | None = Query(None),
    series: str | None = Query(None),
):
    """Per-series monthly seasonal indices (bounded). Requires a series key."""
    key = _series_key(cur, product_surr, store_surr, series)
    if key is None:
        raise HTTPException(status_code=400, detail="provide product_surr/store_surr or series")
    return demand_service.demand_seasonality(cur, *key)


@router.get("/analytics/demand/dow", response_model=DemandDow)
def demand_dow(
    cur=Depends(_get_db),
    scope_type: str | None = Query(None, pattern="^(all|category|dept|state|store)$"),
):
    """DOW profile indices per scope type."""
    return demand_service.demand_dow(cur, scope_type=scope_type)


# --- Forecast ------------------------------------------------------------------ #
@router.get("/forecast/accuracy", response_model=ForecastAccuracy)
def forecast_accuracy(cur=Depends(_get_db)):
    """Per-model accuracy with support counts + 64-series pilot caveat."""
    return forecast_service.accuracy(cur)


@router.get("/forecast/models", response_model=ForecastModels)
def forecast_models(cur=Depends(_get_db)):
    """Model registry + selection + support + pilot caveat."""
    return forecast_service.models(cur)


@router.get("/forecast/series", response_model=ForecastSeries)
def forecast_series(cur=Depends(_get_db), series: str | None = Query(None)):
    """One series' 28-day final forecast (bounded, no fan-out)."""
    if not series:
        raise HTTPException(status_code=400, detail="series is required (product:store)")
    return forecast_service.series(cur, series)


# --- Inventory ----------------------------------------------------------------- #
@router.get("/inventory/summary", response_model=InventorySummary)
def inventory_summary(cur=Depends(_get_db)):
    """Aggregate baseline simulated inventory state (bounded)."""
    return inventory_service.summary(cur)


@router.get("/inventory/horizon", response_model=InventoryHorizon)
def inventory_horizon(cur=Depends(_get_db), series: str | None = Query(None)):
    """Per-day simulated inventory horizon for one series (28 bounded rows)."""
    if not series:
        raise HTTPException(status_code=400, detail="series is required (product:store)")
    return inventory_service.horizon(cur, series)


@router.get("/inventory/policy", response_model=InventoryPolicy)
def inventory_policy(cur=Depends(_get_db)):
    """Static baseline inventory policy snapshot."""
    return inventory_service.policy(cur)


# --- Scenario ------------------------------------------------------------------ #
@router.get("/scenario/runs", response_model=ScenarioRuns)
def scenario_runs(cur=Depends(_get_db)):
    """Run id → scenario metadata / status / records processed."""
    return scenario_service.runs(cur)


@router.get("/scenario/deltas", response_model=ScenarioDeltas)
def scenario_deltas(cur=Depends(_get_db)):
    """Per-scenario vs-baseline delta aggregates (simulated)."""
    return scenario_service.deltas(cur)


@router.get("/scenario/comparison", response_model=ComparisonStatus)
def scenario_comparison(cur=Depends(_get_db)):
    """Explicit empty state for fact_scenario_comparison (0 rows)."""
    return scenario_service.comparison(cur)


# --- Risk ---------------------------------------------------------------------- #
@router.get("/risk/rankings", response_model=RiskRankings)
def risk_rankings(
    cur=Depends(_get_db),
    risk_type: str = Query(..., pattern="^(stockout|excess)$"),
    tier: str | None = Query(None, pattern="^(Low|Medium|High|Critical)$"),
    product: str | None = Query(None),
    store: str | None = Query(None),
    department: str | None = Query(None),
    category: str | None = Query(None),
    state: str | None = Query(None),
    region: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
):
    """Paginated, filtered stockout/excess risk ranking (simulated, deterministic
    by native risk_rank). Dimension drill-down is server-side."""
    filters = {
        "tier": tier,
        "product": product,
        "store": store,
        "department": department,
        "category": category,
        "state": state,
        "region": region,
    }
    try:
        return risk_service.rankings(
            cur, risk_type=risk_type, filters=filters, page=page, page_size=page_size
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/risk/drivers", response_model=RiskDrivers)
def risk_drivers(cur=Depends(_get_db), series: str | None = Query(None)):
    """risk_components evidence breakdown for one series (simulated)."""
    if not series:
        raise HTTPException(status_code=400, detail="series is required (product:store)")
    return risk_service.drivers(cur, series)


# --- helpers ------------------------------------------------------------------- #
def _series_key(cur, product_surr, store_surr, series):
    """Resolve a series identity from any supported input form."""
    if product_surr is not None and store_surr is not None:
        return product_surr, store_surr
    if series is not None:
        from ..services.db import parse_series

        key = parse_series(cur, series)
        if key is not None:
            return key.product_surr_id, key.store_surr_id
    return None