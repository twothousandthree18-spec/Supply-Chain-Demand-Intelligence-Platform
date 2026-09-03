# Scenario Engine — Design

**Phase 0 — Design only. No scenarios have been executed.**

## 1. Purpose

Re-run forecasting + inventory simulation under alternative business conditions to answer "what if" questions for operational decision support.

## 2. Planned Scenarios

| # | Scenario | Input change |
|---|---|---|
| 1 | **Baseline** | No change — reference case. |
| 2 | **Demand +10%** | Scale forecast demand by +10% over horizon. |
| 3 | **Demand −15%** | Scale forecast demand by −15% over horizon. |
| 4 | **Increased supplier lead time** | Increase lead-time assumption (e.g., base + N days) and re-derive safety stock/reorder point. |
| 5 | **Promotion / demand uplift** | Apply a temporal uplift to event/promotion periods (e.g., calendar event days uplift). |

## 3. Inputs

- Baseline entity-level forecasts.
- Inventory `assumption_set`.
- Scenario definition (parameter deltas). Each scenario is a named, versioned config.

## 4. Calculations

Re-run the inventory simulation (and, where relevant, re-derive safety stock / reorder point) using the scenario-adjusted demand and/or adjusted assumptions. Every scenario uses a fresh `fact_inventory_simulation` run tagged with its `scenario_id`.

## 5. Outputs

Per scenario, per entity:
- Forecasted demand series (adjusted).
- Inventory position over time.
- Projected stockout count/units.
- Excess inventory.
- Service level achieved.
- Days of inventory.
- Reorder frequency/quantity.

Plus a **comparison table** of affected KPIs across scenarios (baseline as reference).

## 6. Affected KPIs (for each scenario)

Forecast accuracy context, service level, stockout risk, excess inventory, days-of-inventory, inventory holding implied, reorder activity.

## 7. Decision Implications

The scenario comparison feeds the DECISION ENGINE and the "Scenario Analysis" dashboard page: e.g., "under Demand +10%, N products fall below target service level and should be reordered sooner"; "under Demand −15%, M products become excess and should be reduced."

## 8. Traceability & Honesty

All scenario outputs inherit `data_provenance = 'simulated'` and reference the exact scenario + assumption set. Results are labeled and never presented as actual outcomes.
