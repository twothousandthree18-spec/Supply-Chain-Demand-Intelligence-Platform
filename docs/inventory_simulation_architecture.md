# Inventory Simulation Architecture

**Phase 3E — Implemented & Production-Populated.** The simulation engine, formulas, contract tests, bounded representative pilot, and the full 30,490-series production run are complete (run_id=9). Every record in `fact_inventory_simulation` carries `data_provenance='simulated'`. Complete outputs: `reports/PHASE_3E_PILOT_OUTPUT.txt` and `reports/PHASE_3E_PRODUCTION_OUTPUT.txt`; phase report: `reports/PHASE_3E_REPORT.md`.

## 1. Purpose

Translate demand forecasts into inventory-relevant quantities so the platform can flag stockout risk, excess inventory, and reorder needs. Because the M5 dataset contains NO actual inventory data (lead times, POs, stockouts), **everything in this layer is simulated and labeled `simulated`.**

## 2. Implemented Calculation Sequence (per product/store)

1. **Simulated starting inventory** — coverage rule: `STARTING_COVERAGE_DAYS` (7) × expected daily demand (Phase 3C `fact_demand_analysis.mean_daily_units`).
2. **Lead time** — fixed `LEAD_TIME_DAYS = 7` (deterministic; distributional lead time is a documented future scenario option).
3. **Service level** — target cycle service level `0.95`, sizing the safety-stock z-factor (`SERVICE_LEVEL_Z = 1.6448536269514722`).
4. **Safety stock** — `z(service_level) × σ(lead-time demand)` where `σ(lead-time) = σ(daily) · √lead_time`, and daily σ comes from Phase 3C `fact_demand_analysis.std_daily_units`.
5. **Reorder point** — `reorder_point = expected lead-time demand + safety_stock` (enforced even when a σ override is supplied).
6. **Inventory position** — `on-hand + on-order − backlog`, tracked daily.
7. **Reorder quantity** — `(s,Q)`: `Q = 7 × expected daily demand`, capped at 28 days of coverage (`REORDER_QTY_MULTIPLE=7`, `MAX_ORDER_QTY_COVERAGE_DAYS=28`). Trigger: place order when `position <= reorder_point`.
8. **Projected stockout** — when on-hand cannot cover demand + carried backorder, record units short and flag the event. Flag is stored at the same precision as `stockout_units` (NUMERIC(14,4)) so `projected_stockout <=> stockout_units > 0`.
9. **Excess inventory** — on-hand above `EXCESS_COVERAGE_DAYS` (28) × expected daily demand.
10. **Outputs** — daily time series of starting inventory, demand forecast, lead-time demand, safety stock, reorder point, inventory position, on-hand, orders placed, reorder qty, stockout flag/units, excess, days of inventory, service level achieved — one record per series per day [1942,1969].

Daily ordering (deterministic): arrivals land → demand + carried backorder served → order placed if position drops at/below the reorder point. Orders placed whose arrival would fall after day 1969 remain in-flight (`final_on_order`), never materializing inside the bounded window.

## 3. Assumptions — Configurable & Documented

All parameters live in `src/inventory/config.py` and are persisted to the `assumption_set` table (baseline row `baseline_service_95_pct`, id=1). Changing any assumption re-runs the whole simulation and re-baselines all outputs.

| Assumption | Value | Config key |
|---|---|---|
| Starting inventory rule | coverage days = 7 | `STARTING_COVERAGE_DAYS` |
| Supplier lead time | fixed = 7 days | `LEAD_TIME_DAYS` |
| Service level (target cycle) | 0.95 | `SERVICE_LEVEL`, `SERVICE_LEVEL_Z` |
| Safety stock formula | z × σ(lead-time demand) | `SAFETY_STOCK_FORMULA` |
| Demand variability source | historical daily σ (`fact_demand_analysis.std_daily_units`) | driver sizing via `policy_from_aggregates` |
| Expected daily demand source | `fact_demand_analysis.mean_daily_units` | driver sizing |
| Reorder policy | (s,Q) | `REORDER_POLICY` |
| Reorder quantity rule | capped coverage days | `REORDER_QTY_MULTIPLE`, `MAX_ORDER_QTY_COVERAGE_DAYS` |
| Reorder point | lead-time demand + safety stock | `REORDER_POINT_FORMULA` |
| Stockout handling | backorder (carried, not lost) | `STOCKOUT_HANDLING` |
| Excess ceiling | 28 days of expected demand | `EXCESS_COVERAGE_DAYS` |
| Horizon | days [1942,1969] (28) | `HORIZON_START_DAY`, `HORIZON_END_DAY` |
| Pilot subset | top-64 by lifetime units | `PILOT_TOP_N` |
| Provenance | `simulated` | `DATA_PROVENANCE_SIMULATED` |

## 4. Provenance

- Every simulated daily record is written with `assumption_set_id` and `data_provenance = 'simulated'`.
- Observed history is used ONLY to size the policy (`fact_demand_analysis` aggregates); the simulated horizon is driven strictly by Phase 3D final forecasts (`fact_forecast`, `is_final`).
- No simulated stockout is ever presented as a real observed event; dashboards must display the assumption set and provenance.

## 5. Outputs (populated, verified)

- `assumption_set` — baseline row (id=1) upserted by the driver.
- `fact_inventory_simulation` — **853,720 rows** (30,490 series × 28 days), all `simulated`; verified: no duplicate (assumption_set, series, day) keys, day coverage exactly 28/series, no negative on-hand / demand / stockout / order quantities, `service_level_achieved ∈ [0,1]`, `projected_stockout <=> stockout_units > 0`.
- Aggregated inventory-risk metrics are printed per run (stockout days/units, excess days, fill rate, achieved service level, replenishment arrivals) and feed the future DECISION ENGINE.

## 6. Bounded Inputs (no 59M observed-fact scan)

- Sizing: `fact_demand_analysis` (30,490 rows) — `mean_daily_units`, `std_daily_units`, `total_units`.
- Demand driver: `fact_forecast` final rows (853,720) for days [1942,1969].
- The driver never reads `fact_daily_sales`.