"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Scenario Engine configuration (single source of truth).

All scenario-layer constants: scenario types, parameter bounds, ranking
weights, risk tiers, priority labels, and the persisted `scenario_rules`
dictionary. Everything is deterministic and mirrors the completed-phase
assumption set (src/inventory/config.py) that every scenario reuses.

Consumption contract (documented in docs/scenario_engine_architecture.md):
  * sizing moments   <- fact_demand_analysis (Phase 3C aggregates; no 59M scan)
  * forecast demand  <- fact_forecast (is_final, days [1942,1969]; Phase 3D)
  * assumption set   <- `assumption_set` id=1 (Phase 3E baseline)
All scenario outputs are SIMULATED (data_provenance='simulated').
"""

from src.inventory import config as inv_config

# --------------------------------------------------------------------------- #
# Reused baseline (Phase 3E assumption set) - never re-derived here.
# --------------------------------------------------------------------------- #
BASE_ASSUMPTION_SET_ID = inv_config.ASSUMPTION_SET_ID           # 1
BASE_ASSUMPTION_SET_NAME = inv_config.ASSUMPTION_SET_NAME       # baseline_service_95_pct
BASE_LEAD_TIME_DAYS = inv_config.LEAD_TIME_DAYS                  # 7.0 (fixed)
BASE_SERVICE_LEVEL = inv_config.SERVICE_LEVEL                    # 0.95
BASE_REORDER_QTY_MULTIPLE = inv_config.REORDER_QTY_MULTIPLE      # 7.0
BASE_MAX_ORDER_QTY_COVERAGE_DAYS = inv_config.MAX_ORDER_QTY_COVERAGE_DAYS  # 28.0
STARTING_COVERAGE_DAYS = inv_config.STARTING_COVERAGE_DAYS       # 7.0
EXCESS_COVERAGE_DAYS = inv_config.EXCESS_COVERAGE_DAYS           # 28.0

# Simulation horizon (bounded; identical to Phase 3E).
HORIZON_START_DAY = inv_config.HORIZON_START_DAY                 # 1942
HORIZON_END_DAY = inv_config.HORIZON_END_DAY                     # 1969
HORIZON_DAYS = inv_config.HORIZON_DAYS                           # 28

# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
DATA_PROVENANCE_SIMULATED = inv_config.DATA_PROVENANCE_SIMULATED  # "simulated"

# --------------------------------------------------------------------------- #
# Scenario types
# --------------------------------------------------------------------------- #
DEMAND_SHOCK = "demand_shock"
LEAD_TIME_CHANGE = "lead_time_change"
SERVICE_LEVEL_CHANGE = "service_level_change"
REORDER_POLICY = "reorder_policy"
STOCKOUT_RISK = "stockout_risk_prioritization"
EXCESS_RISK = "excess_inventory_prioritization"
ACTION_TRADEOFF = "action_tradeoff"

# A per-series simulation scenario re-runs the inventory engine under the
# scenario's policy/demand settings (produces a daily trace + summary).
SIMULATION_SCENARIOS = (
    DEMAND_SHOCK,
    LEAD_TIME_CHANGE,
    SERVICE_LEVEL_CHANGE,
    REORDER_POLICY,
)

# A ranking scenario scores and ranks a result population (baseline or another
# scenario's run) by a documented risk formulation.
RANKING_SCENARIOS = (
    STOCKOUT_RISK,
    EXCESS_RISK,
)

# A comparison scenario consolidates a baseline population vs a target
# population into a structured action trade-off (no fabricated financials).
COMPARISON_SCENARIOS = (ACTION_TRADEOFF,)

SCENARIO_TYPES = SIMULATION_SCENARIOS + RANKING_SCENARIOS + COMPARISON_SCENARIOS

# --------------------------------------------------------------------------- #
# Parameter semantics (validated in validation.py)
# --------------------------------------------------------------------------- #
# Demand shock treats the change as UNPLANNED: the per-day forecast demand is
# scaled (multiplier = 1 + demand_adjustment_pct) while the safety-stock /
# reorder-point sizing stays at the baseline assumption set. A shock is, by
# definition, not yet reflected in the plan, so this reveals the true stress.
DEMAND_SHOCK_PLANNED = False
DEMAND_SHOCK_PCT_MIN = -0.999      # demand cannot drop below ~0 (exclusive)
DEMAND_SHOCK_PCT_MAX = 10.0        # +1000% sanity cap

LEAD_TIME_MIN_DAYS = 1.0           # discrete arrival scheduling needs >= 1
SERVICE_LEVEL_TARGET_MIN = 0.0     # exclusive bounds for the (0,1) target
SERVICE_LEVEL_TARGET_MAX = 1.0

# --------------------------------------------------------------------------- #
# Ranking weights (documented; sum to 1 after optional overrides)
# --------------------------------------------------------------------------- #
STOCKOUT_RISK_WEIGHTS = {
    "volume": 0.15,          # demand volume rank (bigger = more harmful)
    "volatility": 0.15,      # demand volatility rank (cv)
    "stockout_prob": 0.30,   # projected stockout probability over the horizon
    "service_gap": 0.20,     # target CSL - achieved CSL (0 when at/above target)
    "urgency": 0.20,         # earliness of the first projected stockout
}

EXCESS_RISK_WEIGHTS = {
    "excess_days_ratio": 0.40,      # share of horizon days in excess
    "positioning_gap": 0.35,        # avg days-of-inventory above the 28-day ceiling
    "excess_unit_efficiency": 0.25, # excess units per unit of demand (0..1)
}

# Risk tiers: score threshold -> label (checked top-down).
RISK_TIERS = (
    (0.70, "Critical"),
    (0.45, "High"),
    (0.25, "Medium"),
    (0.00, "Low"),
)

# --------------------------------------------------------------------------- #
# Decision-engine contract (implementation lands in a later step)
# --------------------------------------------------------------------------- #
# Mirrors the fact_replenishment_recommendation.recommendation CHECK constraint.
RECOMMENDATION_ACTION_LABELS = (
    "REORDER",
    "MONITOR",
    "REDUCE INVENTORY",
    "HIGH STOCKOUT RISK",
    "EXCESS INVENTORY",
    "NO ACTION REQUIRED",
)
PRIORITY_LABELS = ("P1", "P2", "P3", "P4")


# --------------------------------------------------------------------------- #
# Persisted reproducible scenario rules (scenario_rules table)
# --------------------------------------------------------------------------- #
RULES = {
    "horizon_start_day": (HORIZON_START_DAY, "First simulated day (1942)."),
    "horizon_end_day": (HORIZON_END_DAY, "Last simulated day (1969)."),
    "horizon_days": (HORIZON_DAYS, "Simulation horizon length (28)."),
    "base_assumption_set_id": (BASE_ASSUMPTION_SET_ID,
                               "Baseline assumption set reused by every scenario (Phase 3E)."),
    "base_lead_time_days": (BASE_LEAD_TIME_DAYS,
                            "Baseline fixed lead time in days (7)."),
    "base_service_level": (BASE_SERVICE_LEVEL,
                           "Baseline cycle service level target (0.95)."),
    "base_reorder_qty_multiple": (BASE_REORDER_QTY_MULTIPLE,
                                  "Baseline reorder quantity multiple in days (7)."),
    "base_max_order_qty_coverage_days": (BASE_MAX_ORDER_QTY_COVERAGE_DAYS,
                                         "Baseline order-quantity coverage cap in days (28)."),
    "demand_shock_planned": (1.0 if DEMAND_SHOCK_PLANNED else 0.0,
                             "Whether a demand shock re-sizes the policy (0=unplanned stress)."),
    "demand_shock_pct_min": (DEMAND_SHOCK_PCT_MIN,
                             "Smallest allowed demand shock (approx -100%)."),
    "demand_shock_pct_max": (DEMAND_SHOCK_PCT_MAX,
                             "Largest allowed demand shock (+1000%)."),
    "lead_time_min_days": (LEAD_TIME_MIN_DAYS,
                           "Minimum enforceable lead time for arrival scheduling."),
    "stockout_w_volume": (STOCKOUT_RISK_WEIGHTS["volume"],
                          "Stockout-risk weight on demand volume rank."),
    "stockout_w_volatility": (STOCKOUT_RISK_WEIGHTS["volatility"],
                              "Stockout-risk weight on volatility rank."),
    "stockout_w_prob": (STOCKOUT_RISK_WEIGHTS["stockout_prob"],
                        "Stockout-risk weight on projected stockout probability."),
    "stockout_w_service_gap": (STOCKOUT_RISK_WEIGHTS["service_gap"],
                               "Stockout-risk weight on the service-level gap."),
    "stockout_w_urgency": (STOCKOUT_RISK_WEIGHTS["urgency"],
                           "Stockout-risk weight on first-stockout urgency."),
    "excess_w_days": (EXCESS_RISK_WEIGHTS["excess_days_ratio"],
                      "Excess-risk weight on the excess-days ratio."),
    "excess_w_positioning": (EXCESS_RISK_WEIGHTS["positioning_gap"],
                             "Excess-risk weight on the inventory positioning gap."),
    "excess_w_efficiency": (EXCESS_RISK_WEIGHTS["excess_unit_efficiency"],
                            "Excess-risk weight on excess units per demand unit."),
    "excess_coverage_days": (EXCESS_COVERAGE_DAYS,
                             "Excess-inventory coverage ceiling in days (28)."),
}