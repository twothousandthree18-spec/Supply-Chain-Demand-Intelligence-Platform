"""Phase 6 typed data contracts — product-area payloads.

Each model mirrors the locked aggregate surfaces (docs/phase5_traceability.md)
and is served by src/web/services/*. Field names are stable; provenance is
always explicit so the presentation layer can render chips and "—".
"""

from datetime import date

from pydantic import BaseModel, Field

from .common import MetricValue, Pagination, Provenance


# --- Executive ----------------------------------------------------------------- #
class HeadlineKpis(BaseModel):
    revenue: MetricValue
    units: MetricValue
    weighted_price: MetricValue
    revenue_wow_pct: MetricValue
    units_wow_pct: MetricValue
    revenue_qoq_pct: MetricValue
    revenue_yoy_pct: MetricValue
    units_yoy_pct: MetricValue


class TrendPoint(BaseModel):
    period: str | int
    units: float
    revenue: float


class ExecutiveSnapshot(BaseModel):
    headline: HeadlineKpis
    revenue_trend: list[TrendPoint] = Field(default_factory=list)


class ContributionRow(BaseModel):
    entity: str
    value: float
    share_pct: float
    rank: int
    provenance: Provenance


class ExecutiveContributions(BaseModel):
    by_product: list[ContributionRow] = Field(default_factory=list)
    by_department: list[ContributionRow] = Field(default_factory=list)
    by_state: list[ContributionRow] = Field(default_factory=list)


class OperationalSignal(BaseModel):
    product: str
    store: str
    risk_type: str
    tier: str
    score: float
    rank: int
    primary_driver: str | None = None
    provenance: Provenance


class SignalSummary(BaseModel):
    stockout_at_risk: int
    excess_at_risk: int
    signals: list[OperationalSignal] = Field(default_factory=list)


# --- Inventory / Scenario (metrics only in this step) -------------------------- #
class ComparisonStatus(BaseModel):
    """Represents the locked fact_scenario_comparison empty state (0 rows)."""

    present: bool
    rows: int = 0
    reason: str = "no action_tradeoff scenario in the production set"


class MetaDoc(BaseModel):
    provenance_contract: dict[str, str]
    limitations: list[str] = Field(default_factory=list)
    empty_states: list[str] = Field(default_factory=list)
    reconcile_anchors: dict[str, int | str | None] = Field(default_factory=dict)
    scenario_run_map: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Demand Intelligence
# --------------------------------------------------------------------------- #
class DatabaseKey(BaseModel):
    """A product × store series key (surrogate ids + human ids for display)."""

    product_surr_id: int
    store_surr_id: int
    product: str | None = None
    store: str | None = None


class DemandRow(BaseModel):
    """One product × store demand-analysis series (observed_full window)."""

    product: str
    store: str
    mean_daily_units: float | None = None
    cv: float | None = None
    volatility_class: str | None = None
    demand_growth_rate: float | None = None
    growth_defined: bool = True
    trend_direction: str | None = None
    trend_effect_pct: float | None = None
    seasonality_strength: float | None = None
    peak_month: int | None = None
    trough_month: int | None = None
    segment_volume: str | None = None
    segment_volatility: str | None = None
    segment_demand: str | None = None
    risk_cell: str | None = None
    risk_category: str | None = None
    provenance: Provenance = Provenance.DERIVED


class DemandSegments(BaseModel):
    """Volume × volatility matrix with risk-category breaks (bounded counts)."""

    risk_category: Provenance = Provenance.DERIVED
    volume_classes: list[str] = Field(default_factory=list)
    volatility_classes: list[str] = Field(default_factory=list)
    matrix: list[dict] = Field(default_factory=list)  # [{volume, volatility, count}]
    risk_breaks: list[dict] = Field(default_factory=list)  # [{risk_category, count}]


class SeasonalMonth(BaseModel):
    month: int
    seasonal_index: float
    obs_weeks: int


class DemandSeasonality(BaseModel):
    series: DatabaseKey
    strength: float | None = None
    has_meaningful_seasonality: bool = False
    peak_month: int | None = None
    trough_month: int | None = None
    monthly_indices: list[SeasonalMonth] = Field(default_factory=list)
    provenance: Provenance = Provenance.DERIVED


class DowPoint(BaseModel):
    scope_type: str
    scope_key: str | None = None
    scope_value: str | None = None
    weekday_num: int
    weekday_name: str
    dow_index: float | None = None
    obs_days: int = 0
    provenance: Provenance = Provenance.DERIVED


class DemandDow(BaseModel):
    scope_type: str
    points: list[DowPoint] = Field(default_factory=list)
    provenance: Provenance = Provenance.DERIVED


# --------------------------------------------------------------------------- #
# Forecast Intelligence
# --------------------------------------------------------------------------- #
class ForecastModel(BaseModel):
    model_id: int
    model_name: str
    model_family: str | None = None
    is_selected: bool = False
    validation_start: int | None = None
    validation_end: int | None = None
    support_series: int = 0
    metrics: dict[str, float | None] = Field(default_factory=dict)
    selection_rationale: str | None = None
    pilot_limited: bool = False
    provenance: Provenance = Provenance.DERIVED


class ForecastModels(BaseModel):
    models: list[ForecastModel] = Field(default_factory=list)
    pilot_series: int | None = None
    model_count: int = 0
    limitation_note: str | None = None


class ForecastAccuracyRow(BaseModel):
    model_id: int
    model_name: str
    support_series: int = 0
    mae: float | None = None
    rmse: float | None = None
    wmae: float | None = None
    wrmse: float | None = None
    abs_error: float | None = None
    bias: float | None = None
    undefined: bool = False
    pilot_limited: bool = False
    provenance: Provenance = Provenance.DERIVED


class ForecastAccuracy(BaseModel):
    rows: list[ForecastAccuracyRow] = Field(default_factory=list)
    selected_model: str | None = None
    pilot_series: int | None = None
    caveat: str | None = None


class ForecastPoint(BaseModel):
    series: DatabaseKey
    forecast_date: int
    forecast_value: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    origin: int | None = None
    horizon: int | None = None
    provenance: Provenance = Provenance.DERIVED


class ForecastSeries(BaseModel):
    series: DatabaseKey | None = None
    points: list[ForecastPoint] = Field(default_factory=list)
    total: int = 0


# --------------------------------------------------------------------------- #
# Inventory Intelligence
# --------------------------------------------------------------------------- #
class InventorySummary(BaseModel):
    series: DatabaseKey | None = None
    on_hand: float | None = None
    on_order: float | None = None
    backorder: float | None = None
    inventory_position: float | None = None
    days_of_inventory: float | None = None
    service_level_achieved: float | None = None
    fill_rate: float | None = None
    stockout_units: float | None = None
    excess_inventory: float | None = None
    safety_stock: float | None = None
    reorder_point: float | None = None
    horizon_days: int = 0
    provenance: Provenance = Provenance.SIMULATED


class InventoryDay(BaseModel):
    series: DatabaseKey | None = None
    day_id: int
    inventory_position: float | None = None
    on_hand: float | None = None
    on_order: float | None = None
    stockout: bool = False
    stockout_units: float | None = None
    days_of_inventory: float | None = None
    provenance: Provenance = Provenance.SIMULATED


class InventoryHorizon(BaseModel):
    series: DatabaseKey | None = None
    days: list[InventoryDay] = Field(default_factory=list)
    total: int = 0


class InventoryPolicy(BaseModel):
    assumption_set_id: int | None = None
    policy_name: str | None = None
    safety_stock_formula: str | None = None
    reorder_policy: str | None = None
    reorder_quantity_rule: str | None = None
    supplier_lead_time_days: float | None = None
    service_level_target: float | None = None
    starting_inventory_rule: str | None = None
    provenance: Provenance = Provenance.SIMULATED


# --------------------------------------------------------------------------- #
# Scenario Intelligence
# --------------------------------------------------------------------------- #
class ScenarioRunStatus(BaseModel):
    scenario_run_id: int
    scenario_id: int
    scenario_name: str
    scenario_type: str | None = None
    assumption_set_id: int | None = None
    status: str
    records_processed: int | None = None
    executed_at: str | None = None
    provenance: Provenance = Provenance.SIMULATED


class ScenarioRuns(BaseModel):
    runs: list[ScenarioRunStatus] = Field(default_factory=list)
    total: int = 0


class ScenarioDelta(BaseModel):
    scenario_run_id: int
    scenario_id: int
    name: str
    scenario_type: str | None = None
    delta_stockout_days: float | None = None
    delta_service_level: float | None = None
    delta_fill_rate: float | None = None
    delta_reorder_frequency: float | None = None
    delta_avg_inventory_position: float | None = None
    delta_excess_days: float | None = None
    delta_avg_days_of_inventory: float | None = None
    series_count: int = 0
    provenance: Provenance = Provenance.SIMULATED


class ScenarioDeltas(BaseModel):
    deltas: list[ScenarioDelta] = Field(default_factory=list)
    total: int = 0


# --------------------------------------------------------------------------- #
# Risk / Operational Insights
# --------------------------------------------------------------------------- #
class RiskRank(BaseModel):
    product: str
    store: str
    risk_rank: int
    risk_score: float | None = None
    risk_tier: str | None = None
    primary_driver: str | None = None
    evidence: dict = Field(default_factory=dict)
    department: str | None = None
    category: str | None = None
    state: str | None = None
    region: str | None = None
    provenance: Provenance = Provenance.SIMULATED


class RiskRankings(BaseModel):
    risk_type: str
    tier: str | None = None
    pagination: Pagination
    items: list[RiskRank] = Field(default_factory=list)


class RiskDrivers(BaseModel):
    series: DatabaseKey | None = None
    risk_rank: int | None = None
    risk_score: float | None = None
    risk_tier: str | None = None
    components: dict = Field(default_factory=dict)
    provenance: Provenance = Provenance.SIMULATED