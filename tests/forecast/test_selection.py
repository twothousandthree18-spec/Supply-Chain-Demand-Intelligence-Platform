"""
Phase 3D - Model-selection logic tests (pure).

The core rule: a more complex (statistical) model is selected for a series ONLY
if it genuinely beats that series' best baseline on the SAME chronological
holdout by at least config.SELECTION_IMPROVEMENT (>=1% relative WMAE). Otherwise
the best baseline is retained. Selection must be deterministic.
"""

import numpy as np
import pytest

from src.forecasting import config, selection


# --------------------------------------------------------------------------- #
# best_baseline
# --------------------------------------------------------------------------- #
def test_best_baseline_lowest_wmae():
    w = {"naive": 5.0, "seasonal_naive": 3.0, "moving_average": 4.0, "weighted_ma": 6.0}
    assert selection.best_baseline(w) == "seasonal_naive"


def test_best_baseline_tie_broken_by_simplest_order():
    w = {"naive": 3.0, "seasonal_naive": 3.0, "moving_average": 3.0, "weighted_ma": 3.0}
    assert selection.best_baseline(w) == "naive"


def test_best_baseline_ignores_none():
    w = {"naive": None, "seasonal_naive": 2.0, "moving_average": None, "weighted_ma": 5.0}
    assert selection.best_baseline(w) == "seasonal_naive"


def test_best_baseline_all_none_returns_none():
    assert selection.best_baseline({"naive": None, "seasonal_naive": None}) is None


# --------------------------------------------------------------------------- #
# statistical_wins
# --------------------------------------------------------------------------- #
def test_statistical_wins_above_margin():
    # base=10.0, stat=8.8 -> (10-8.8)/10 = 0.12 >= 0.01 -> True
    assert selection.statistical_wins(8.8, 10.0) is True


def test_statistical_wins_below_margin():
    # base=10.0, stat=9.9 -> 0.01 exactly == margin -> True (>=); use 9.95 -> 0.005
    assert selection.statistical_wins(9.95, 10.0) is False


def test_statistical_wins_at_margin_qualifies():
    # exactly at the margin with float-safe arithmetic -> qualifies (>= margin)
    assert selection.statistical_wins(95.0, 100.0, improvement=0.05) is True
    # just below the margin -> fails (0.04 < 0.05)
    assert selection.statistical_wins(96.0, 100.0, improvement=0.05) is False


def test_statistical_wins_no_improvement_when_worse():
    assert selection.statistical_wins(11.0, 10.0) is False


def test_statistical_wins_none_or_zero_base():
    assert selection.statistical_wins(None, 10.0) is False
    assert selection.statistical_wins(8.0, None) is False
    assert selection.statistical_wins(8.0, 0.0) is False     # degenerate zero base


def test_statistical_wins_custom_margin():
    # 20% improvement beats a 15% margin requirement
    assert selection.statistical_wins(8.0, 10.0, improvement=0.15) is True
    # 10% improvement fails a 20% margin requirement
    assert selection.statistical_wins(9.0, 10.0, improvement=0.20) is False


def test_statistical_wins_default_margin_matches_config():
    assert config.SELECTION_IMPROVEMENT == 0.01


# --------------------------------------------------------------------------- #
# select_for_series
# --------------------------------------------------------------------------- #
def test_select_returns_best_baseline_when_no_stat_candidate():
    w = {"naive": 9.0, "seasonal_naive": 3.0, "moving_average": 6.0, "weighted_ma": 5.0}
    assert selection.select_for_series(w, statistical_subset=False) == "seasonal_naive"


def test_select_does_not_pick_stat_when_not_subset():
    w = {"naive": 10.0, "seasonal_naive": 9.0, "moving_average": 9.0,
         "weighted_ma": 9.0, "ets_holt_winters": 2.0, "sarima": 3.0}
    # even though a stat model looks great, non-pilot series cannot use it; the
    # best BASELINE (seasonal_naive, 9.0) is selected instead.
    assert selection.select_for_series(w, statistical_subset=False) == "seasonal_naive"


def test_select_picks_stat_only_when_it_genuinely_beats_baseline():
    w = {"naive": 10.0, "seasonal_naive": 9.5, "moving_average": 9.0,
         "weighted_ma": 9.2, "ets_holt_winters": 3.0, "sarima": 4.0}
    # best baseline = moving_average (9.0); ETS (3.0) beats it by >1% -> selected
    assert selection.select_for_series(w, statistical_subset=True) == "ets_holt_winters"


def test_select_retains_baseline_when_stat_does_not_genuinely_win():
    w = {"naive": 10.0, "seasonal_naive": 9.0, "moving_average": 8.9,
         "weighted_ma": 9.0, "ets_holt_winters": 8.95, "sarima": 8.93}
    # best baseline = moving_average (8.9); stat 8.95/8.93 beat it by <1% -> reject
    assert selection.select_for_series(w, statistical_subset=True) == "moving_average"


def test_select_picks_better_of_two_wins_stat_models():
    w = {"naive": 10.0, "seasonal_naive": 9.0, "moving_average": 9.0,
         "weighted_ma": 9.0, "ets_holt_winters": 4.0, "sarima": 3.0}
    # both beat baseline; SARIMA is better -> selected
    assert selection.select_for_series(w, statistical_subset=True) == "sarima"


def test_select_falls_back_to_naive_when_no_baseline_scored():
    w = {"naive": None, "seasonal_naive": None, "moving_average": None, "weighted_ma": None}
    assert selection.select_for_series(w, statistical_subset=False) == "naive"


def test_select_deterministic():
    w = {"naive": 10.0, "seasonal_naive": 9.5, "moving_average": 9.0,
         "weighted_ma": 9.2, "ets_holt_winters": 3.0, "sarima": 4.0}
    a = selection.select_for_series(w, statistical_subset=True)
    b = selection.select_for_series(w, statistical_subset=True)
    assert a == b


# --------------------------------------------------------------------------- #
# champion_model
# --------------------------------------------------------------------------- #
def test_champion_most_frequent():
    sel = ["naive", "naive", "moving_average", "moving_average", "moving_average"]
    assert selection.champion_model(sel) == "moving_average"


def test_champion_tie_broken_by_fixed_order():
    sel = ["naive", "seasonal_naive", "naive", "seasonal_naive"]
    # tie -> simpler (earlier in BASELINE_ORDER) wins
    assert selection.champion_model(sel) == "naive"


def test_champion_empty_returns_none():
    assert selection.champion_model([]) is None
