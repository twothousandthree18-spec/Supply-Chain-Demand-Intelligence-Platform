"""
Phase 4 - Ranking logic tests (scenarios 5 & 6) and comparison (7).

Requirement coverage:
  * stockout-risk prioritization ranking
  * excess-inventory prioritization (demand-justified vs inefficient positioning)
  * deterministic reproducibility of scores/tiers/ranks
  * action-trade-off comparison with explicit assumptions (no fabricated cost)
"""

import math

import numpy as np
import pytest

from src.scenario import config
from src.scenario.contract import ScenarioDefinition
from src.scenario.scenarios import (
    aggregate_population,
    compute_tradeoff,
    percentile_ranks,
    run_baseline,
    run_scenario,
    score_and_rank,
    tier_for,
)

from _helpers import make_series  # noqa: E402


def _defn(scenario_type, params, name="s"):
    return ScenarioDefinition(scenario_name=name, scenario_type=scenario_type,
                              params=params)


def _population(n=6, seed_mean=8.0, seed_std=3.0, spike_every=2):
    """A small deterministic population with varying stockout exposure."""
    pop = []
    for i in range(n):
        mean = seed_mean + i
        std = seed_std + i * 0.5
        spike = 55.0 if i % spike_every == 0 else 0.0
        forecast = [mean] * 28
        if spike:
            forecast[5] = spike if i % spike_every == 0 else mean
        series = make_series(pid=i + 1, sid=1, mean=mean, std=std,
                             total=1000.0 * (i + 1), forecast=forecast)
        pop.append(run_baseline(series))
    return pop


# --------------------------------------------------------------------------- #
# percentile ranks (deterministic, bounded)
# --------------------------------------------------------------------------- #
def test_percentile_ranks_distinct_and_bounded():
    ranks = percentile_ranks([1.0, 2.0, 3.0, 4.0])
    assert ranks == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])
    assert all(0.0 <= r <= 1.0 for r in ranks)


def test_percentile_ranks_ties_share_rank():
    ranks = percentile_ranks([10.0, 10.0, 20.0])
    # two-way tie at the bottom shares rank 1.5 -> (1.5-1)/2 = 0.25
    assert ranks[0] == pytest.approx(0.25)
    assert ranks[1] == pytest.approx(0.25)
    assert ranks[2] == pytest.approx(1.0)


def test_percentile_ranks_empty_and_nan_safe():
    assert percentile_ranks([]) == []
    ranks = percentile_ranks([None, float("nan"), 1.0])
    assert ranks[2] == pytest.approx(1.0)   # NaN coerced to 0 (ranked lowest)


# --------------------------------------------------------------------------- #
# stockout risk prioritization
# --------------------------------------------------------------------------- #
def test_stockout_risk_ranking_deterministic_and_ordered():
    pop = _population(6)
    a = score_and_rank(pop, config.STOCKOUT_RISK)
    b = score_and_rank(pop, config.STOCKOUT_RISK)
    assert [(r.product_surr_id, r.risk_rank, r.risk_score) for r in a] == \
        [(r.product_surr_id, r.risk_rank, r.risk_score) for r in b]
    ranks = [r.risk_rank for r in a]
    assert ranks == list(range(1, len(a) + 1))
    scores = [r.risk_score for r in a]
    assert scores == sorted(scores, reverse=True)


def test_stockout_risk_score_components():
    pop = _population(6)
    ranked = score_and_rank(pop, config.STOCKOUT_RISK)
    r = ranked[0]
    assert set(r.components) == {"volume_rank", "volatility_rank",
                                 "stockout_prob", "service_gap", "urgency"}
    # score is the weighted sum of the documented components (normalized);
    # weight keys are human-readable, component keys carry a _rank suffix
    w = config.STOCKOUT_RISK_WEIGHTS
    lookup = {"volume": "volume_rank", "volatility": "volatility_rank",
              "stockout_prob": "stockout_prob",
              "service_gap": "service_gap", "urgency": "urgency"}
    expected = sum(w[k] * r.components[lookup[k]] for k in w)
    assert r.risk_score == pytest.approx(min(1.0, expected), abs=1e-6)
    assert r.risk_tier in ("Low", "Medium", "High", "Critical")
    assert r.data_provenance == config.DATA_PROVENANCE_SIMULATED


def test_stockout_risk_empty_population():
    assert score_and_rank([], config.STOCKOUT_RISK) == []


def test_stockout_risk_rejects_wrong_input():
    pop = _population(2)
    with pytest.raises(Exception):
        score_and_rank(pop, config.DEMAND_SHOCK)


def test_stockout_risk_weights_normalized():
    pop = _population(6)
    ranked = score_and_rank(pop, config.STOCKOUT_RISK,
                            weights={"stockout_prob": 10.0, "urgency": 10.0})
    assert ranked[0].risk_score <= 1.0 + 1e-9


def test_stockout_risk_catches_tier_ordering():
    assert tier_for(1.0) == "Critical"
    assert tier_for(0.70) == "Critical"
    assert tier_for(0.69) == "High"
    assert tier_for(0.45) == "High"
    assert tier_for(0.25) == "Medium"
    assert tier_for(0.05) == "Low"


# --------------------------------------------------------------------------- #
# excess-inventory prioritization
# --------------------------------------------------------------------------- #
def test_excess_ranking_distinguishes_positioning_inefficiency():
    # two series with the SAME excess units, different demand:
    #   - high demand: excess is proportional to demand (justified-ish)
    #   - low demand:  excess is disproportionate (inefficient positioning)
    def with_demand(mean, avg_doi):
        # craft metrics directly: avg_days_of_inventory is the lever
        forecast = [mean] * 28
        return {
            "product_surr_id": int(mean * 100),
            "store_surr_id": 1,
            "metrics": {
                "total_units_hist": mean * 28,
                "total_demand": mean * 28,
                "excess_days": 20,
                "total_excess_units": mean * 28,   # one full horizon of excess
                "avg_days_of_inventory": avg_doi,
                "cv": 0.2,
                "data_provenance": config.DATA_PROVENANCE_SIMULATED,
            },
            "policy": None,
            "scenario": None,
            "deltas": None,
            "risk_score": None, "risk_tier": None, "risk_rank": None,
            "components": None,
        }

    from src.scenario.scenarios import ScenarioSeriesResult
    low_demand = ScenarioSeriesResult(**with_demand(1.0, 40.0))
    high_demand = ScenarioSeriesResult(**with_demand(50.0, 40.0))
    ranked = score_and_rank([low_demand, high_demand], config.EXCESS_RISK)
    # low-demand series is ranked FIRST (inefficient positioning), even though
    # its absolute excess units are far smaller than the high-demand series.
    assert ranked[0].product_surr_id == low_demand.product_surr_id
    assert ranked[0].risk_rank == 1
    # demand-justified flag is present for both entries
    assert all("demand_justified" in r.components for r in ranked)


def test_excess_ranking_deterministic():
    pop = _population(6)
    a = score_and_rank(pop, config.EXCESS_RISK)
    b = score_and_rank(pop, config.EXCESS_RISK)
    assert [(r.product_surr_id, r.risk_rank, r.risk_score) for r in a] == \
        [(r.product_surr_id, r.risk_rank, r.risk_score) for r in b]


# --------------------------------------------------------------------------- #
# action trade-off (scenario 7)
# --------------------------------------------------------------------------- #
def test_tradeoff_operational_metrics_no_cost_default():
    baseline = _population(6)
    target = []
    for r in baseline:
        series = make_series(pid=r.product_surr_id, sid=r.store_surr_id,
                             mean=_moments(r)[0], std=_moments(r)[1],
                             total=r.metrics["total_units_hist"])
        target.append(run_scenario(
            series, _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": 0.25}),
            baseline_result=r))

    t = compute_tradeoff(baseline, target,
                         _defn(config.ACTION_TRADEOFF,
                               {"target_scenario": "demand_shock_p25"}))
    assert t.data_provenance == config.DATA_PROVENANCE_SIMULATED
    assert t.monetary is None                       # no cost fabricated
    assert t.n_series == len(baseline)
    assert "delta_total_stockout_units" in t.stockout_impact
    assert "delta_avg_inventory_position" in t.inventory_exposure
    assert "delta_series_below_target" in t.service_level_effect
    assert "delta_total_excess_units" in t.excess_impact
    assert any("no financial savings are fabricated" in a for a in t.assumptions)


def test_tradeoff_with_explicit_cost_assumptions():
    baseline = _population(4)
    target = []
    for r in baseline:
        series = make_series(pid=r.product_surr_id, sid=r.store_surr_id,
                             mean=_moments(r)[0], std=_moments(r)[1],
                             total=r.metrics["total_units_hist"])
        target.append(run_scenario(
            series, _defn(config.DEMAND_SHOCK, {"demand_adjustment_pct": -0.30}),
            baseline_result=r))
    t = compute_tradeoff(
        baseline, target,
        _defn(config.ACTION_TRADEOFF,
              {"target_scenario": "down30",
               "unit_holding_cost": 0.1, "stockout_penalty_per_unit": 2.0}))
    assert t.monetary is not None
    assert "baseline_holding_cost_exposure" in t.monetary
    assert "delta_stockout_cost" in t.monetary
    # cost figures are derived from explicit inputs (not fabricated)
    assert t.monetary["stockout_penalty_per_unit"] == pytest.approx(2.0)


def test_tradeoff_deltas_are_exact_differences():
    baseline = _population(3)
    target = []
    for r in baseline:
        series = make_series(pid=r.product_surr_id, sid=r.store_surr_id,
                             mean=_moments(r)[0], std=_moments(r)[1],
                             total=r.metrics["total_units_hist"])
        target.append(run_scenario(
            series, _defn(config.SERVICE_LEVEL_CHANGE,
                          {"service_level_target": 0.90}),
            baseline_result=r))
    t = compute_tradeoff(baseline, target,
                         _defn(config.ACTION_TRADEOFF,
                               {"target_scenario": "sl90"}))
    assert t.service_level_effect["delta_series_below_target"] == (
        t.service_level_effect["scenario_series_below_target"]
        - t.service_level_effect["baseline_series_below_target"])
    assert t.stockout_impact["delta_total_stockout_units"] == pytest.approx(
        t.stockout_impact["scenario_total_stockout_units"]
        - t.stockout_impact["baseline_total_stockout_units"], abs=1e-6)


def test_aggregate_population_counts():
    pop = _population(4)
    agg = aggregate_population(pop)
    assert agg["n_series"] == 4
    assert agg["total_stockout_days"] == sum(r.metrics["stockout_days"] for r in pop)
    assert agg["series_with_stockout"] == sum(
        1 for r in pop if r.metrics["stockout_days"] > 0)


def _moments(r):
    return r.metrics["expected_daily_demand"], r.metrics["daily_sigma"]