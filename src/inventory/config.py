"""
Supply Chain & Demand Intelligence Platform
Phase 3E - Inventory simulation configuration (assumption set).

Single source of truth for the operational assumptions that drive safety-stock
/ reorder-point sizing and the rolling inventory simulation. All assumption
values are SIMULATED (the M5 dataset contains NO observed inventory, lead
times, purchase orders, or stockouts), so every derived quantity is labeled
data_provenance='simulated' and must never be presented as observed.

Every value is explicit and documented in
docs/inventory_simulation_architecture.md. The persisted assumption set is
written to the `assumption_set` table for reproducibility.
"""

# --------------------------------------------------------------------------- #
# Reproducible operating assumptions
# --------------------------------------------------------------------------- #
# Unique, stable identifier for the baseline assumption set (see DB PK).
ASSUMPTION_SET_ID = 1
ASSUMPTION_SET_NAME = "baseline_service_95_pct"
ASSUMPTION_SET_DESCRIPTION = (
    "Baseline Phase 3E assumptions: 7-day coverage starting inventory, "
    "fixed 7-day lead time, 95% cycle service level, safety stock = z x sigma "
    "of lead-time demand, reorder point = lead-time demand + safety stock, "
    "(s,Q) with a cap on order quantity. All simulated."
)

# --------------------------------------------------------------------------- #
# Starting inventory rule
# --------------------------------------------------------------------------- #
# Rule: starting on-hand = STARTING_COVERAGE_DAYS * average historical daily
# demand, so the first day's position is ~N days of projected demand coverage,
# not an arbitrary large constant. Computed per series from observed history.
STARTING_INVENTORY_RULE = "coverage_days"
STARTING_COVERAGE_DAYS = 7.0

# --------------------------------------------------------------------------- #
# Lead-time rule/distribution
# --------------------------------------------------------------------------- #
# Fixed, single-value lead time in days (deterministic; a distributional lead
# time is a documented future scenario option, not used in the baseline).
LEAD_TIME_RULE = "fixed"
LEAD_TIME_DAYS = 7.0

# --------------------------------------------------------------------------- #
# Service-level target (cycle service level) - sizes the safety-stock z factor
# --------------------------------------------------------------------------- #
SERVICE_LEVEL = 0.95          # 95% cycle service level target
# z(0.95) = 1.64485362695... (standard-normal quantile). Kept explicit for
# reproducibility and used by the z_service() helper.
SERVICE_LEVEL_Z = 1.6448536269514722

# --------------------------------------------------------------------------- #
# Safety-stock formula
# --------------------------------------------------------------------------- #
# safety_stock = z(service_level) * sigma_lead_time_demand
#   sigma_lead_time_demand = sigma_daily_demand * sqrt(LEAD_TIME_DAYS)
#   sigma_daily_demand     = documented estimator of daily demand variability
#                            (e.g., residual std / MAD from forecast error, or
#                            historical daily std on intermittent series).
SAFETY_STOCK_FORMULA = "z_x_sigma_lead_time_demand"
SAFETY_STOCK_ESTIMATOR = "forecast_error_sigma"   # documented estimator choice

# --------------------------------------------------------------------------- #
# Reorder point
# --------------------------------------------------------------------------- #
# reorder_point = expected lead-time demand + safety stock
REORDER_POINT_FORMULA = "lead_time_demand_plus_safety_stock"

# --------------------------------------------------------------------------- #
# Reorder policy & quantity
# --------------------------------------------------------------------------- #
# (s,Q): when inventory position drops at/below the reorder point s, place an
# order of size Q. Q = REORDER_QTY_MULTIPLE * expected daily demand, capped at
# MAX_ORDER_QTY_COVERAGE_DAYS of coverage. Bounded so we never emit absurd
# order quantities from volatile M5 series.
REORDER_POLICY = "(s,Q)"
REORDER_QTY_MULTIPLE = 7.0                # order ~7 days of expected demand
MAX_ORDER_QTY_COVERAGE_DAYS = 28.0        # cap order size at 28 days of demand
REORDER_QUANTITY_RULE = "capped_coverage_days"

# --------------------------------------------------------------------------- #
# Stockout / backorder handling
# --------------------------------------------------------------------------- #
# Unfilled demand is carried forward as a backorder (not lost). Inventory
# position = on_hand + on_order - backorder. Backorders are satisfied first on
# replenishment arrival.
STOCKOUT_HANDLING = "backorder"

# --------------------------------------------------------------------------- #
# Excess-inventory definition
# --------------------------------------------------------------------------- #
# A series has excess inventory on a day when projected on-hand exceeds the
# target coverage ceiling (EXCESS_COVERAGE_DAYS of expected daily demand).
# excess_inventory = max(0, on_hand - EXCESS_COVERAGE_DAYS * expected_daily_demand)
EXCESS_COVERAGE_DAYS = 28.0

# --------------------------------------------------------------------------- #
# Bounded representative pilot subset (mirrors Phase 3D)
# --------------------------------------------------------------------------- #
# The pilot runs the SAME driver code over the top-N product/store series by
# lifetime observed units, so the pilot validates the exact production path
# (sizing from fact_demand_analysis aggregates, forecast-driven demand, and
# every persisted record) before the full 30,490-series run.
PILOT_TOP_N = 64

# --------------------------------------------------------------------------- #
# Simulation horizon
# --------------------------------------------------------------------------- #
# Use the Phase 3D forecast horizon: forecasting produced final forecasts for
# days FINAL_FORECAST_START..FINAL_FORECAST_END (origin 1941, horizon 28).
# The simulation advances day-by-day over this same bounded horizon.
HORIZON_DAYS = 28
HORIZON_START_DAY = 1942
HORIZON_END_DAY = HORIZON_START_DAY + HORIZON_DAYS - 1      # 1969

# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
# Every inventory quantity is SIMULATED (M5 has no observed inventory); this is
# the single source for the value written to data_provenance columns.
DATA_PROVENANCE_SIMULATED = "simulated"

# --------------------------------------------------------------------------- #
# Expected (point) demand estimator
# --------------------------------------------------------------------------- #
# Where a per-day point forecast is not available, the expected daily demand
# used for coverage sizing is Mean Absolute Demand over the observed history
# (a robust central tendency on sparse M5 series). See formulas.expected_daily_demand().
DEMAND_CENTRAL_ESTIMATOR = "mean"

# --------------------------------------------------------------------------- #
# Persisted assumption-set rows (written to `assumption_set` by the driver).
# --------------------------------------------------------------------------- #
ASSUMPTION_SET_ROWS = {
    "baseline_service_95_pct": {
        "name": ASSUMPTION_SET_NAME,
        "description": ASSUMPTION_SET_DESCRIPTION,
        "starting_inventory_rule": STARTING_INVENTORY_RULE,
        "supplier_lead_time_days": LEAD_TIME_DAYS,
        "service_level": SERVICE_LEVEL,
        "safety_stock_formula": SAFETY_STOCK_FORMULA,
        "reorder_policy": REORDER_POLICY,
        "reorder_quantity_rule": REORDER_QUANTITY_RULE,
        "demand_adjustment": 1.0,
    }
}
