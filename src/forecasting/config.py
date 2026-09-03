"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Forecasting configuration.

Single source of truth for the forecasting constants used by the Phase 3D
driver and the forecast-layer tests. These are persisted to the
`forecast_rules` table for reproducibility. All values are explicit and
documented in docs/forecasting_architecture.md.

Observed M5 window: days d_1 .. d_1941 (66,927,173 units over 30,490
product x store series). Forecast target is the M5 28-day evaluation horizon
d_1942 .. d_1969.
"""

# --------------------------------------------------------------------------- #
# Clock / window (M5 day indexes; date_id == M5 day index)
# --------------------------------------------------------------------------- #
OBSERVED_START = 1
OBSERVED_END = 1941            # last observed day in the loaded warehouse
FINAL_HORIZON = 28             # forecast horizon (M5 evaluation length)
FINAL_FORECAST_START = 1942    # first day of the final (future) forecast
FINAL_FORECAST_END = OBSERVED_END + FINAL_HORIZON    # 1969

# --------------------------------------------------------------------------- #
# Chronological validation (single-origin, past -> future, no leakage)
# --------------------------------------------------------------------------- #
# Train on [1, TRAIN_END], hold out [VALIDATION_START, VALIDATION_END] which
# are the last 28 observed days. NEVER a random split.
TRAIN_END = OBSERVED_END - FINAL_HORIZON          # 1913
VALIDATION_START = TRAIN_END + 1                  # 1914
VALIDATION_END = OBSERVED_END                     # 1941
VALIDATION_HORIZON = FINAL_HORIZON                # 28

# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
SEASONALITY = 7                # weekly seasonality (7-day lag), M5 daily units
MA_WINDOW = 7                  # moving-average window (days)
MIN_TRAIN_POINTS = 28          # need >= one season of history to emit a forecast

# --------------------------------------------------------------------------- #
# Bounded statistical subset (do NOT blindly fit 30,490 models)
# --------------------------------------------------------------------------- #
# Advanced models (ETS/Holt-Winters, SARIMA) are fitted ONLY on this bounded,
# deterministic subset (top-N product/store series by lifetime observed units,
# plus all "smooth/meaningful" pilot decisions). Kept small so the pilot is
# affordable and fully deterministic.
PILOT_TOP_N = 64

# --------------------------------------------------------------------------- #
# Model selection rule
# --------------------------------------------------------------------------- #
# A more complex (statistical) model is selected only if it genuinely beats the
# best baseline on the SAME series/holdout by at least this relative WMAE margin
# (>=1%). Otherwise the best baseline is selected (conservative, honest).
SELECTION_IMPROVEMENT = 0.01

# --------------------------------------------------------------------------- #
# Prediction intervals
# --------------------------------------------------------------------------- #
PI_Z = 1.96                    # ~95% two-sided interval on residual std
MIN_PI_ABS = 0.0               # floors below zero are clamped to zero

# --------------------------------------------------------------------------- #
# Persisted reproducible rules (forecast_rules table)
# --------------------------------------------------------------------------- #
RULES = {
    "final_horizon": (FINAL_HORIZON, "Final forecast horizon in days (28)."),
    "observed_end": (OBSERVED_END, "Last observed day index (1941)."),
    "train_end": (TRAIN_END, "Chronological training end (last day used to train for validation)."),
    "validation_start": (VALIDATION_START, "First day of the chronological holdout (1914)."),
    "validation_end": (VALIDATION_END, "Last day of the chronological holdout (1941)."),
    "seasonality": (SEASONALITY, "Weekly seasonality lag in days (7)."),
    "ma_window": (MA_WINDOW, "Moving-average window in days (7)."),
    "min_train_points": (MIN_TRAIN_POINTS, "Min training length (days) to emit a forecast."),
    "pilot_top_n": (PILOT_TOP_N, "Bounded statistical pilot subset size (top-N series)."),
    "selection_improvement": (SELECTION_IMPROVEMENT, "Min relative WMAE gain for a statistical model to beat the best baseline."),
    "pi_z": (PI_Z, "Standard-normal multiplier for ~95% prediction interval."),
}
