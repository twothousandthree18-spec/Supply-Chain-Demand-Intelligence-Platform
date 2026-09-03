# Scenario Engine Architecture (Phase 4)

**Status:** Steps 1-3 complete (architecture + contracts, DB schema, pure calculations) AND the Phase 4 production scenario run is complete (run_id=11, 7 scenarios, 213,430 result rows). The decision-engine/recommendation layer and dashboards are deferred to a later step.

## Overview

The scenario engine is a **pure, deterministic, DB-free** calculation layer that runs on top of the completed Phase 2-3E outputs. It answers "what if" questions by re-running the existing inventory simulation engine under alternative policy/demand assumptions, then comparing the scenario result against a baseline to produce operational deltas.

The engine **reuses** (never re-implements) the existing inventory sizing logic (`policy_from_aggregates`) and simulation engine (`simulate_series`). Forecasting logic is never touched.

## Design Principles

1. **DB-free calculators:** Every function in `src/scenario/` is pure — identical inputs always produce identical outputs, with no I/O, no database connections, no randomness.
2. **Bounded inputs:** Moments come from `fact_demand_analysis` (Phase 3C, 30,490 rows). Forecast vectors come from `fact_forecast.is_final` (Phase 3D, 28 days). The assumption set is `id=1` (Phase 3E baseline). No 59M-row `fact_daily_sales` scans.
3. **Deterministic reproducibility:** Re-running the same `ScenarioDefinition` (same name, type, params, assumption set) against the same input data produces byte-identical output.
4. **No fabricated financials:** All outputs are operational metrics (units, days, service levels, order quantities). Monetary figures appear **only** when explicit cost assumptions are supplied in the scenario params.
5. **No modification of completed phases:** Phase 2-3E row counts are never disturbed. The only structural change is adding columns to the empty `fact_replenishment_recommendation` table.

## Supported Scenarios

| # | Type | What It Does | Policy Impact |
|---|------|-------------|---------------|
| 1 | `demand_shock` | Scales forecast demand by `(1+pct)`, clamped ≥0 | Baseline policy stays; reveals true stress |
| 2 | `lead_time_change` | Changes `lead_time_days` and re-derives safety stock / reorder point | Policy rebuilt with new LT |
| 3 | `service_level_change` | Changes the target cycle service level and re-derives safety stock / reorder point | Policy rebuilt with new SL |
| 4 | `reorder_policy` | Changes the (s,Q) sizing: reorder-qty multiple and coverage cap | Policy rebuilt with new Q |
| 5 | `stockout_risk_prioritization` | Scores and ranks series by projected stockout risk using 5 weighted components | Ranking only (no simulation) |
| 6 | `excess_inventory_prioritization` | Scores and ranks series by excess inventory risk using 3 weighted components | Ranking only (no simulation) |
| 7 | `action_tradeoff` | Structured scenario-vs-baseline comparison at population level | Comparison only (no simulation) |

## Architecture

```
src/scenario/
├── config.py          # Scenario types, bounds, weights, tiers, RULES dict
├── contract.py        # Typed dataclasses (ScenarioDefinition, ScenarioSeriesResult, etc.)
├── validation.py      # Parameter validation (bounds, combos, weights)
├── scenarios.py       # Pure calculators (apply_demand_shock, build_policy, run_baseline, etc.)
└── run_scenario.py    # Production driver: DB pulls, batched writes, CLI (NOT part of the pure layer)
```

### Input Flow

```
fact_demand_analysis (Phase 3C)  ──→  SizingMoments  ──→  build_policy()  ──→  InventoryPolicy
fact_forecast.is_final (Phase 3D) ──→  forecast[28]   ──→  run_scenario()  ──→  simulate_series()
assumption_set id=1 (Phase 3E)   ──→  baseline params
```

### Output Flow

```
run_scenario()  ──→  ScenarioSeriesResult
    ├─ metrics: dict    (mirrors fact_scenario_result columns)
    ├─ deltas: dict     (scenario - baseline for each metric)
    └─ policy: InventoryPolicy

score_and_rank()  ──→  ScenarioSeriesResult[] with risk_score, risk_tier, risk_rank
compute_tradeoff() ──→  ActionTradeoff (aggregate comparison)
```

## Baseline Reproduction

The baseline is reproduced via `run_baseline()`, which:
1. Sizes a policy via `build_policy(moments)` — identical to Phase 3E's `policy_from_aggregates`.
2. Runs `simulate_series(forecast, policy)` — the same engine.
3. Returns a `ScenarioSeriesResult` with `scenario=None` (baseline marker).

This is **byte-identical** to the Phase 3E output without re-scanning the simulated fact table, because the same bounded inputs flow through the same engine.

## Demand Shock Semantics

A demand shock is **UNPLANNED**: the daily forecast is scaled by `(1+pct)` while the policy (safety stock, reorder point) stays at the baseline assumption set. This reveals the true stress on the committed plan — the plan has not yet been adjusted for the shock.

| Shock | Meaning |
|-------|---------|
| +20% | Demand increases 20% above baseline forecast |
| -50% | Demand drops 50% below baseline forecast |
| -100% | Demand collapses to zero (clamped) |

## Ranking Components

### Stockout Risk (5 components)
- **volume_rank:** Normalized rank of total historical units (bigger = more harmful)
- **volatility_rank:** Normalized rank of demand CV (more volatile = more risky)
- **stockout_prob:** Projected stockout days / horizon length
- **service_gap:** max(0, target CSL - achieved CSL)
- **urgency:** 1 - (first stockout offset / horizon) — earlier stockout = more urgent

### Excess Inventory Risk (3 components)
- **excess_days_ratio:** Excess days / horizon length
- **positioning_gap:** max(0, (avg_days_of_inventory - 28) / 28), capped at 1.0
- **excess_unit_efficiency:** min(1, total_excess_units / total_demand)

Weights are normalized to sum to 1, and each component is normalized to [0,1] via empirical percentile ranks.

## Risk Tiers

| Score Range | Tier |
|-------------|------|
| ≥ 0.70 | Critical |
| ≥ 0.45 | High |
| ≥ 0.25 | Medium |
| < 0.25 | Low |

## Determinism Guarantees

1. No randomness — all calculators are pure functions of their inputs.
2. No I/O — no database connections, no file reads, no network calls.
3. Reordering is deterministic — ties are broken by `(product_surr_id, store_surr_id)` ascending.
4. Ranking scores are bounded in [0,1] — weighted sums are clipped.
5. `ScenarioDefinition` is frozen — params cannot be mutated mid-calculation.

## Known Limitations (deferred to later steps)

- **No decision-engine logic** — the `Recommendation` dataclass is contract-only; the logic that populates `fact_replenishment_recommendation` is deferred to the decision-engine step.
- **No dashboard/web UI** — the scenario engine is a backend calculation layer.
- **No `action_tradeoff` in the current production set** — the shipped 7-scenario production set contains baseline, 4 simulations, and 2 rankings (no comparison scenario), so `fact_scenario_comparison` has 0 rows by design.

## Production Run (run_id=11)

- **Pipeline:** `scenario_engine`, `etl_run_log.run_id=11`, status `success`, 213,430 rows.
- **Scope:** 30,490 product-store series × 7 scenarios; inputs from `fact_demand_analysis` (30,490), `fact_forecast.is_final` (853,720 rows for the horizon) — no `fact_daily_sales` scan.
- **Outputs:** `fact_scenario_result` = 213,430 rows (30,490 per scenario, all `data_provenance='simulated'`, no duplicate `(run, product, store)` keys); `scenario` = 7 defs; `scenario_rules` = 21; `fact_scenario_run` = 7.
- **Provenance:** every scenario output carries `data_provenance='simulated'`.
- **Idempotency/batch:** batched writes (chunk 5,000, periodic commit) and idempotent scenario/rules upserts enabled.
