"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Model-selection logic (pure).

Selection rule (documented in docs/forecasting_architecture.md):

  * For every series, the candidate models are scored on the SAME chronological
    holdout. Baselines are scored on every product/store series; statistical
    models (ETS/SARIMA) are scored ONLY on the bounded pilot subset.
  * The per-series best baseline is the baseline with the lowest holdout WMAE
    (ties broken in favor of the simplest model order).
  * A statistical model is selected for a series ONLY if it beats that series'
    best baseline by at least config.SELECTION_IMPROVEMENT relative WMAE margin.
    Otherwise the best baseline is selected.
  * `is_selected` on a registered model is TRUE when that model actually wins
    the largest share of the series on which it was evaluated (the champion),
    or, for a statistical model, when it genuinely beats the best baseline over
    its pilot subset (so an honest statistical win is recorded even if it wins
    only a fraction of series).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from . import config

BASELINE_ORDER = ("naive", "seasonal_naive", "moving_average", "weighted_ma")


def best_baseline(wmae_by_baseline: Dict[str, Optional[float]]) -> Optional[str]:
    """Return the baseline model with the lowest (finite) holdout WMAE.

    Ties are broken by BASELINE_ORDER (simpler baseline wins).
    """
    best = None
    best_val = None
    for name in BASELINE_ORDER:
        v = wmae_by_baseline.get(name)
        if v is None or not _finite(v):
            continue
        if best_val is None or v < best_val:
            best_val = v
            best = name
    return best


def statistical_wins(
    stat_wmae: Optional[float],
    baseline_wmae: Optional[float],
    improvement: Optional[float] = None,
) -> bool:
    """A statistical model is selected only if it genuinely beats the best
    baseline by at least the relative WMAE improvement margin (default 1%)."""
    margin = config.SELECTION_IMPROVEMENT if improvement is None else improvement
    if stat_wmae is None or baseline_wmae is None:
        return False
    if not (_finite(stat_wmae) and _finite(baseline_wmae) and baseline_wmae > 0):
        return False
    return (baseline_wmae - stat_wmae) / baseline_wmae >= margin


def select_for_series(
    series_wmae: Dict[str, Optional[float]],
    statistical_subset: bool = False,
    improvement: Optional[float] = None,
) -> str:
    """Choose the model for one series.

    Returns the selected model name. Baselines are always candidates; statistical
    candidates (ets_holt_winters, sarima) apply only when statistical_subset=True
    (i.e., the series is in the bounded pilot subset) AND the statistical model
    genuinely beats the best baseline per the rule.
    """
    best_base = best_baseline(series_wmae)
    if best_base is None:
        # no baseline scored (e.g., degenerate series) -> fall back to naive
        return "naive"
    best_base_val = series_wmae.get(best_base)

    if statistical_subset:
        cand = None
        cand_val = None
        for m in ("ets_holt_winters", "sarima"):
            v = series_wmae.get(m)
            if statistical_wins(v, best_base_val, improvement):
                if cand_val is None or v < cand_val:
                    cand_val = v
                    cand = m
        if cand is not None:
            return cand
    return best_base


def champion_model(per_series_selection: Sequence[str]) -> Optional[str]:
    """Most-frequently-selected model across series (ties -> first in fixed order)."""
    counts: Dict[str, int] = {}
    for m in per_series_selection:
        counts[m] = counts.get(m, 0) + 1
    if not counts:
        return None
    tiebreak_order = BASELINE_ORDER + ("ets_holt_winters", "sarima")
    return max(counts, key=lambda m: (counts[m], -tiebreak_order.index(m)))


def _finite(v) -> bool:
    return v is not None and v == v
