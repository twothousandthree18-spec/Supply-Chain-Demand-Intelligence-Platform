# Phase 4 — Steps 1-3 Report

**Date:** 2026-09-01  
**Status:** Steps 1-3 COMPLETE (architecture + contracts, DB schema, pure calculations, tests, docs)

---

## Summary

Phase 4 Steps 1-3 deliver the **scenario engine** — a pure, deterministic, DB-free calculation layer that runs "what if" scenarios on top of the completed Phase 2-3E outputs. No production scenario runs, no dashboards, and no decision-engine logic are included in this step.

---

## What Was Built

### Step 1: Architecture + Contracts

**Files created:**
| File | Purpose |
|------|---------|
| `src/scenario/__init__.package` | Package marker |
| `src/scenario/config.py` | Scenario types, parameter bounds, ranking weights, risk tiers, RULES dict |
| `src/scenario/contract.py` | Typed dataclasses: `ScenarioDefinition`, `SizingMoments`, `SeriesInput`, `ScenarioSeriesResult`, `ActionTradeoff`, `Recommendation`, `ScenarioValidationError` |
| `src/scenario/validation.py` | Parameter validation: bounds, required params, invalid combos, weight sums |

**Design decisions:**
- Demand shock is **UNPLANNED**: scales forecast by `(1+pct)`, policy stays baseline.
- All calculators are pure (no I/O, no randomness, no DB).
- `ScenarioDefinition` is frozen dataclass — params cannot be mutated.
- `Recommendation` dataclass is contract-only (decision logic deferred).
- `build_reproducibility()` records input snapshots + effective params for every run.

### Step 2: Database Objects + Schema

**Files created:**
| File | Purpose |
|------|---------|
| `sql/schema/07_phase4_objects.sql` | Tables: `scenario`, `scenario_rules`, `fact_scenario_run`, `fact_scenario_result`, `fact_scenario_comparison`. ALTERs: `fact_replenishment_recommendation` (adds `scenario_id`, `scenario_run_id`, `priority`, `priority_label`) |
| `sql/indexes/42_phase4_indexes.sql` | Indexes: `ix_scen_run_scen_exec`, `ix_scen_res_run`, `ix_scen_res_ent`, `ix_scen_res_rank`, `ix_rec_scenario`, `ix_rec_ent_decision` |

**Schema applied to DB:** All 5 tables + ALTERs + indexes created successfully.

**Verification:** All Phase 2-3E row counts unchanged:
- `fact_product_store_demand`: 30,490
- `fact_demand_analysis`: 30,490
- `fact_forecast`: 853,720
- `fact_inventory_simulation`: 853,720
- `fact_replenishment_recommendation`: 0 (structure-only, untouched)
- `assumption_set`: 1

### Step 3: Pure Scenario Calculations

**Files created:**
| File | Purpose |
|------|---------|
| `src/scenario/scenarios.py` | Pure calculators: `apply_demand_shock`, `build_policy`, `run_baseline`, `run_scenario`, `percentile_ranks`, `tier_for`, `score_and_rank`, `aggregate_population`, `compute_tradeoff` |

**Key behaviors:**
- Scenarios 1-4 re-run the inventory engine under alternative assumptions.
- Scenarios 5-6 score and rank a population by risk using weighted percentile-rank components.
- Scenario 7 produces a structured scenario-vs-baseline comparison (aggregate).
- `run_baseline()` reproduces Phase 3E byte-identically from the same bounded inputs.
- All outputs carry `data_provenance="simulated"`.

---

## Bugs Found & Fixed

### Source bugs (in step-1 code)

| Bug | Fix |
|-----|-----|
| `ScenarioDefinition.param` was decorated `@property` — calling `definition.param("key")` would fail with `TypeError` (property getter receives only `self`). | Removed `@property` — `param()` is now a plain method. |
| `score_and_rank()` used weight keys (`"volume"`, `"volatility"`) to index into components dict (`"volume_rank"`, `"volatility_rank"`) — would `KeyError` on every stockout-risk ranking. | Added `component_lookup` mapping in `score_and_rank()` to translate weight keys to component keys. |

### Stale test (Phase 3A)

| Bug | Fix |
|-----|-----|
| `test_phase3_foundation.py::test_phase3_tables_empty` asserted `fact_forecast` / `fact_inventory_simulation` were empty (0 rows). These tables are now populated by Phases 3D/3E. | Replaced with `test_phase3_facts_populated_by_completed_phases` asserting the locked row counts. |

---

## Test Suite

### Scenario unit tests (52 tests, all pass)

```
tests/scenario/
├── conftest.py              # sys.path setup
├── _helpers.py              # make_series fixture (unique module name to avoid conftest collision)
├── test_validation.py       # 14 tests: bounds, combos, weights, rejection
├── test_calculations.py     # 16 tests: demand shock, lead-time, SL, reorder, deltas, determinism
├── test_ranking.py          # 12 tests: percentile ranks, stockout risk, excess risk, tradeoff
└── test_contract.py         # 10 tests: DB-free check, frozen contracts, provenance, action labels
```

### SQL schema tests (9 tests, all pass)

```
tests/sql/test_phase4_scenario_schema.py  # 9 tests: table existence, empty state, ALTER columns,
                                          #   CHECK constraints, Phase 2-3E intact, rules structure
```

### Full regression (265 passing)

| Suite | Count | Status |
|-------|-------|--------|
| inventory (tests/inventory) | 109 | PASS |
| scenario (tests/scenario) | 52 | PASS |
| SQL (tests/sql) | 104 | PASS |
| **Total** | **265** | **ALL PASS** |

---

## Documentation

| File | Purpose |
|------|---------|
| `docs/scenario_engine_architecture.md` | Architecture, supported scenarios, design principles, ranking components, determinism guarantees |
| `docs/decision_engine_architecture.md` | Decision-engine contract, recommendation action labels, priority labels, DB schema, traceability |
| `reports/PHASE_4_STEPS_1_3_REPORT.md` | This report |

---

## What Is NOT Included (deferred to later steps)

- [ ] Production scenario driver (reads from DB, writes to `fact_scenario_run/result/comparison`)
- [ ] `scenario_rules` row insertion (INSERT from `config.RULES`)
- [ ] Decision-engine logic (maps scores+deltas → action labels + priorities → `Recommendation`)
- [ ] Dashboard / web UI / frontend
- [ ] `fact_replenishment_recommendation` row population
- [ ] Presentation layer

---

## Files Changed (not created)

| File | Change |
|------|--------|
| `src/scenario/contract.py` | Removed `@property` from `ScenarioDefinition.param` |
| `src/scenario/scenarios.py` | Added `component_lookup` in `score_and_rank()` |
| `tests/sql/test_phase3_foundation.py` | Updated stale empty-table assertion to final-state row counts |
