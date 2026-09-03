# Phase 3E — Inventory Simulation: Completion / Progress Report

**Status:** COMPLETE — the inventory-simulation engine is implemented, formula-locked, and fully unit-tested (109 passed), the representative pilot completed successfully, and the bounded production run (run_id=9, all 30,490 series) populated `fact_inventory_simulation` with verified outputs. Phase 3E is **COMPLETE**.

---

## 1. Phase 3E Scope

Phase 3E delivers the inventory-simulation layer on top of the forecasting layer (Phase 3D). Because the M5 dataset contains **no real inventory records**, every inventory quantity is a documented simulation:

- **Per product/store series:** translate the Phase 3D final forecast (days 1942–1969) into a daily inventory state machine: starting inventory (coverage rule), lead-time demand, safety stock, reorder point, reorder quantity, inventory position, on-hand, orders placed/arrivals, backorders, stockouts, excess, days of inventory, achieved service level, fill rate.
- **Formula-locked assumptions** in `src/inventory/config.py`, persisted to `assumption_set` (baseline id=1) for reproducibility and scenario re-runs.
- **Bounded pilot first** (top-64 series by lifetime units, `--pilot-only`, no DB writes), then a **single bounded production run** of all 30,490 series with batched/resumable writes.
- **Simulated provenance** on every written record; observed history used only for sizing aggregates (`fact_demand_analysis`, 30,490 rows); demand driver strictly the Phase 3D final forecasts.

## 2. Status Summary

| Area | Status |
|---|---|
| Phase 3E DDL (`02_facts.sql` fact_inventory_simulation, `03_metadata.sql` assumption_set) | Already applied |
| Inventory package (`src/inventory/*`) | Implemented |
| Inventory test suite | **109 passed, 0 failed** |
| Driver source defects found & fixed | Yes (see §4) |
| Representative pilot (post-fix) | **Completed successfully — captured** (see §5) |
| Production inventory run | **COMPLETED** — run_id=9, SUCCESS (see §6) |
| `fact_inventory_simulation` / `assumption_set` populated | **YES** — verified (see §7) |
| Phase 2 / 3B / 3C / 3D intact after run | **YES** — verified (see §7) |
| Docs updated | `docs/inventory_simulation_architecture.md` **DONE**; this report |

## 3. Implementation Completed

- `src/inventory/config.py` — single source of truth: coverage/lifetime assumptions, lead time 7, target CSL 0.95 (z=1.64485), safety-stock formula, (s,Q) policy, reorder-qty coverage cap 28, excess ceiling 28, horizon [1942,1969], `PILOT_TOP_N = 64`, `simulated` provenance.
- `src/inventory/simulation.py` — pure engine: `InventoryPolicy`, `InventoryRecord`, `simulate_series`, `compute_policy` (safety stock = z·σ·√LT; `rop = round(lt_demand + safety, 6)`), and `policy_from_aggregates(expected_daily_demand, daily_sigma, ...)` which builds a policy from Phase 3C aggregates with **no 59M-row history scan**.
- `src/inventory/run_inventory_simulation.py` — bounded, resumable, FK-safe driver: `pull_sizing` (fact_demand_analysis), `pull_forecasts` (fact_forecast `is_final`, days 1942–1969), `build_policy`, `simulate_all` (every series), independent `validate_trace` replay (transitions, reorder triggers, arrivals, backorders, stockouts per record), `upsert_assumption_set` (ON CONFLICT (name) DO UPDATE), `_write_production` (batched `executemany` chunk 5000, commit every 8 chunks, idempotent DELETE+INSERT for the assumption set), ETL run-log start/abandoned/failure handling, and a read-only `--pilot-only` mode with a determinism spot check.

### Tests
`tests/inventory/` incl. `test_simulation_contract.py` — state-machine transitions, policy math (safety stock, ROP, (s,Q)), DDL-precision contract (`projected_stockout <=> stockout_units > 0` at NUMERIC(14,4)), sigma_override consistency, `policy_from_aggregates` equivalence, validation trace, negative-input rejection.

**Test suite result: 109 passed, 0 failed.**

## 4. Genuine Source Defects Found & Fixed (no assertions weakened)

1. `simulation.compute_policy` — the reorder point ignored a supplied `sigma_override`, so a caller-sized safety stock did not flow into `rop`. Fixed: `rop = round(lt_demand + safety, 6)` is computed from the (possibly overridden) per-day sigma. Regression test added.
2. `simulation.simulate_series` record emission — `projected_stockout` was derived from the raw float unmet; sub-4dp residual noise (≈1e-5 units) produced `projected_stockout=TRUE` with `stockout_units=0.0000` at the DDL precision, violating the stored contract. Found in STEP-7 DB verification (2 rows of 853,720). Fixed: flag is derived from the DDL-rounded value (`stockout_units_r4 = _R4(step.stockout_units)`, flag iff `> 0.0`). Regression test added.
3. Driver-development validation bugs (caught by the built-in `validate_trace` before any write): starting-inventory comparison needed the pre-arrival on-hand snapshot, and on-order was not decremented on arrival. Both fixed in the driver; the independent trace replay validates every emitted record.

## 5. Representative Pilot (`--pilot-only`)

- **Subset:** top-64 series by lifetime units (`config.PILOT_TOP_N = 64`), sized from `fact_demand_analysis`; 1,792 final forecast rows pulled (28 × 64).
- **Read-only:** no DB writes (branch returns before any write statement).
- **Validation:** all 64 series simulated and **independently replayed** from emitted records (transitions, reorder triggers, arrivals, backorders, stockouts). Determinism spot check: first series (711,5) re-ran byte-identical.
- **Result per pilot output:**

| Metric | Value |
|---|---|
| Series simulated | 64 |
| Day-rows | 1,792 |
| Reorder triggers (series-days) | 314 |
| Replenishment arrivals (units) | 66,916.77 |
| Stockout days (series-days) | 119 |
| Stockout units | 7,568.60 |
| Excess-inventory days | 0 |
| Mean fill rate | 0.9982 (min 0.9228, max 1.0000) |
| Mean achieved service level | 0.9336 (target 0.9500) |
| Series with ≥1 stockout | 27 of 64 |
| Series with ≥1 replenishment | 64 of 64 |

- **Runtime:** 0.5 s; exit code 0; full capture in `reports/PHASE_3E_PILOT_OUTPUT.txt`.
- **Observation (not a defect):** pilot mean achieved cycle service level 0.9336 vs 0.95 target. The target is a policy input; achieved CSL is governed by real forecast variability, finite 28-day horizon, and polynomial breakdown effects — documented as a planning gap for scenario/decision layers.

## 6. Production Inventory Run (bounded driver)

Driver run without `--pilot-only`, once, after all fixes. Complete stdout/stderr captured to `reports/PHASE_3E_PRODUCTION_OUTPUT.txt`.

- **run_id = 9**, status `success`, 853,720 day-rows written, **runtime ≈ 349.8 s**.
- **Series:** all **30,490** product/store series; horizon **[1942,1969]** (28 days), driven by Phase 3D final forecasts.
- **Write strategy:** batched `executemany` (chunk 5000, commit every 8 chunks), idempotent DELETE+INSERT scoped to `assumption_set_id=1`, results-before-FK-parent (`assumption_set` upserted first) — **not** a single giant transaction.
- **Provenance:** all rows `data_provenance='simulated'`, `assumption_set_id=1`.

## 7. Final Verification (lightweight, post-production)

No rerun of simulation and no scan of the 59M-row observed fact. Queries hit only metadata + derived tables.

| Check | Result |
|---|---|
| `fact_inventory_simulation` total / distinct series / days per series | 853,720 / 30,490 / 28 (min=max) |
| day_id range | [1942, 1969] |
| duplicate (assumption_set, series, day) | 0 |
| rows with assumption_set_id=1 / provenance simulated / other | 853,720 / 853,720 / 0 |
| service_level_achieved outside [0,1] | 0 |
| negative on_hand / demand / stockout / order qty | 0 |
| **projected_stockout consistency** (`<=> stockout_units > 0`) | **0** violations |
| assumption_set baseline row | exists (id=1) |
| `etl_run_log` inventory runs / latest status | 2 / success (run_id=9) |
| **Phase 2/3B/3C/3D intact** | `fact_daily_sales` est. 59,181,164; `fact_product_store_demand` 30,490; `fact_demand_analysis` 30,490; `fact_forecast` 853,720; `fact_forecast_evaluation` 122,088; `model_registry` 6; `mv_weekly_sales` est. 8,480,577; `fact_demand_seasonality` 359,181; demand_analysis_rules 16; forecast_rules 11 |
| Inventory test suite | **109 passed, 0 failed** |

## 8. What Was NOT Done in This Session

- No scenario / decision-engine / dashboard work (future phases — this phase only delivers simulation + assumption/risk outputs).
- No rerun or modification of Phase 2 / 3B / 3C / 3D; observed data untouched (`fact_daily_sales` unchanged, no observed-window writes).
- No 59M-row scans; inputs are bounded to `fact_demand_analysis` (30,490) and final forecasts (853,720).
- No new risk table was created — risk outputs ride inside `fact_inventory_simulation` + the printed per-run aggregates (stockouts, excess, fill rate, achieved CSL).

## 9. Known Limitations

- **All inventory quantities are simulated** (no real M5 inventory exists): starting inventory, lead times, orders, and stockouts are modeled artifacts, not observations. Never present them as real events.
- **Fixed 7-day lead time** and **fixed (s,Q) policy**; distributional lead time and alternate policies are documented scenario/decision-layer extensions, all reproducible via `assumption_set`.
- **Achieved CSL ≈ target** only on average; per-series achieved CSL varies with forecast error (pilot mean 0.9336 vs 0.95 target).
- **Final on-order does not materialize** inside the bounded window (orders beyond day 1969 remain in flight); horizon effects are intrinsic to the bounded simulation.

## 10. Acceptance Checklist

| Criterion | Status |
|---|---|
| Policy math formula-locked + config single source of truth | DONE (config + tests) |
| Safety stock / reorder point / (s,Q) formulas | Implemented + tested |
| Daily state machine (arrivals, demand, backorder, reorder, stockout, excess) | Implemented + tested |
| `projected_stockout` consistent with stored `stockout_units` at DDL precision | Implemented + tested + 0 DB violations |
| `policy_from_aggregates` sizes policies without a 59M scan | Implemented + tested |
| Inventory test suite | **109 passed, 0 failed** |
| Bounded representative pilot (read-only, validated, deterministic) | **DONE** — captured |
| Production run (all 30,490 series, batched/resumable, FK-safe) | **DONE** — run_id=9 SUCCESS |
| `assumption_set` seeded (baseline_service_95_pct) | DONE (id=1) |
| `fact_inventory_simulation` populated + fully verified | DONE (853,720 rows, all checks pass) |
| Phase 2/3B/3C/3D intact after run | DONE — counts unchanged |
| `docs/inventory_simulation_architecture.md` updated | DONE |
| Scenario / decision / dashboard phases | Not started (out of scope for 3E) |

**Phase 3E is COMPLETE:** the inventory-simulation machinery is implemented, formula-locked, unit-tested (109 passed), the representative pilot is captured, and the production snapshot (run_id=9, 853,720 simulated day-rows across all 30,490 series) is populated and verified with zero contract violations.