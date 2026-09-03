"""
Supply Chain & Demand Intelligence Platform
Phase 3C - Demand analysis configuration.

Single source of truth for the thresholds used by demand segmentation,
volatility classification, intermittency, trend direction and the
volume x volatility risk matrix. Thresholds are expressed here as constants
so they are fully reproducible; they are also persisted to the
`demand_analysis_rules` table by the Phase 3C driver.

Formulas & rationale: docs/demand_analysis.md
"""

# --------------------------------------------------------------------------- #
# Volume segmentation (quantile policy)
# --------------------------------------------------------------------------- #
# Volume is segmented on total demand using data-driven terciles across all
# product x store series. The quantile cut-points are computed from the data
# and persisted to demand_analysis_rules (keys: volume_quantile_low, _high).
VOLUME_QUANTILES = (1.0 / 3.0, 2.0 / 3.0)
VOLUME_LABELS = ("Low", "Medium", "High")

# --------------------------------------------------------------------------- #
# Volatility segmentation (CV = std / mean at daily grain)
# --------------------------------------------------------------------------- #
CV_LOW = 0.50      # below -> Low volatility
CV_HIGH = 1.00     # at/above -> High volatility; between -> Medium
VOLATILITY_RANK = {"Low": 1, "Medium": 2, "High": 3}
VOLATILITY_LABELS = ("Low", "Medium", "High")

# --------------------------------------------------------------------------- #
# Demand-pattern classification (zero-demand ratio)
#   zero_demand_ratio = zero_demand_days / series_length_days
# --------------------------------------------------------------------------- #
ZERO_RATIO_ERRATIC = 0.50
ZERO_RATIO_LUMPY = 0.75
ZERO_RATIO_INTERMITTENT = 0.90
DEMAND_LABELS = ("Smooth", "Erratic", "Lumpy", "Intermittent")

# --------------------------------------------------------------------------- #
# Trend direction (normalized relative effect of the OLS slope)
#   trend_effect_pct = trend_slope * span_days / mean_daily_units * 100
#   guard: mean below TREND_MIN_MEAN or span below TREND_MIN_SPAN -> 'flat'
# --------------------------------------------------------------------------- #
TREND_UP_PCT = 10.0        # +10% relative growth across the series -> increasing
TREND_DOWN_PCT = -10.0     # -10% -> decreasing; in between -> flat
TREND_MIN_MEAN = 1e-6      # avoid division blow-up on ~zero mean
TREND_MIN_SPAN = 30        # need at least 30 days span for a trend to be meaningful

# --------------------------------------------------------------------------- #
# Growth guard (recent vs prior, weekly)
#   demand_growth_rate = recent_4wk_mean / prior_4wk_mean - 1
# --------------------------------------------------------------------------- #
GROWTH_EPSILON = 1e-9      # prior mean at/below this -> denominator ~ 0 -> undefined

# --------------------------------------------------------------------------- #
# Seasonality meaningfulness
# --------------------------------------------------------------------------- #
SEASON_MIN_ACTIVE_MONTHS = 10   # need >= 10 calendar months with positive weekly demand
SEASON_MIN_STD = 1e-6           # monthly seasonal indices must have non-trivial spread
# A series has "meaningful" calendar seasonality when it has enough active months
# AND its seasonal strength (CV of monthly indices) is positive and the series is
# not too sparse (n_active_months threshold above already enforces that).

# --------------------------------------------------------------------------- #
# Risk matrix (volume x volatility)
#   risk_index = volume_rank * volatility_rank   (1..9)
# --------------------------------------------------------------------------- #
RISK_CRITICAL = 7     # index >= 7 -> Critical
RISK_HIGH = 4         # index >= 4 -> High
RISK_MODERATE = 2     # index >= 2 -> Moderate ; else Low
RISK_LABELS = ("Critical", "High", "Moderate", "Low")

# Rule rows written to demand_analysis_rules (for reproducibility).
RULES = {
    "volume_quantile_low": (VOLUME_QUANTILES[0], "Volume tercile cut (low/medium)."),
    "volume_quantile_high": (VOLUME_QUANTILES[1], "Volume tercile cut (medium/high)."),
    "cv_low": (CV_LOW, "Below this CV the series is Low volatility."),
    "cv_high": (CV_HIGH, "At/above this CV the series is High volatility."),
    "zero_ratio_erratic": (ZERO_RATIO_ERRATIC, "Zero-demand ratio >= this -> Erratic demand."),
    "zero_ratio_lumpy": (ZERO_RATIO_LUMPY, "Zero-demand ratio >= this -> Lumpy demand."),
    "zero_ratio_intermittent": (ZERO_RATIO_INTERMITTENT, "Zero-demand ratio >= this -> Intermittent demand."),
    "trend_up_pct": (TREND_UP_PCT, "Relative trend effect >= +this% -> increasing."),
    "trend_down_pct": (TREND_DOWN_PCT, "Relative trend effect <= this% -> decreasing."),
    "trend_min_mean": (TREND_MIN_MEAN, "Min mean required for trend effect normalization."),
    "trend_min_span": (TREND_MIN_SPAN, "Min series span (days) for a meaningful trend."),
    "growth_epsilon": (GROWTH_EPSILON, "Prior mean at/below this -> growth undefined (zero denom)."),
    "season_min_active_months": (SEASON_MIN_ACTIVE_MONTHS, "Min active calendar months for meaningful seasonality."),
    "risk_critical": (RISK_CRITICAL, "Risk index >= this -> Critical."),
    "risk_high": (RISK_HIGH, "Risk index >= this -> High."),
    "risk_moderate": (RISK_MODERATE, "Risk index >= this -> Moderate; else Low."),
}
