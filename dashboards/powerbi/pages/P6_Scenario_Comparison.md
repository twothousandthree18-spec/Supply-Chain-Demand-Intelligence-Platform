# Page 6 — Scenario Comparison

**Intent:** Compare the 7 alternative supply-chain scenarios (scenario ids 9–15) against the baseline on key
outcome measures (stockout, service, excess, fill, avg inventory position), and quantify delta vs baseline.
A dedicated `action_tradeoff` table (`fact_scenario_comparison`) is **not** populated for this 7-scenario set
(0 rows, by design). This page **must render an explicit informed comparison from `FactScenarioResult`** to
avoid a fabricated tradeoff, and show an **explicit "no tradeoff table" empty-state** wherever such a pivot
would be expected.

**Primary sources:** `FactScenarioResult` (213,430 = 30,490 × 7 runs), `DimScenario` (ids 9–15 with
`scenario_type`), `DimScenarioRun`, `DimAssumptionSet`, `DimProduct/DimStore/DimDepartment/DimCategory`.

**Provenance:** simulated (all).

---

## Scenario measure leaderboard (V1–V5)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V1 | Total Stockout Units | `Total Stockout Units` | `DimScenario[scenario_name]` | Bar |
| V2 | Avg Service Level | `Avg Service Level` | `DimScenario[scenario_name]` | Bar |
| V3 | Total Excess Days | `Total Excess Days` | `DimScenario[scenario_name]` | Bar |
| V4 | Fill Rate | `Fill Rate` | `DimScenario[scenario_name]` | Bar |
| V5 | Avg Inventory Position | `Avg Inventory Position` | `DimScenario[scenario_name]` | Bar |

- Compare baseline vs `demand_shock`, `lead_time_change`, `service_level_change`, `reorder_policy`
  (ids 10–14) and the two rank runs (`stockout_risk_prioritization`, `excess_inventory_prioritization`, ids 15, 9? —
  **use `scenario_type` not ids for safety**).
- **Baseline** = `DimScenario[scenario_type]="baseline"`.

## Scenario delta table (V6)
- **Visual:** matrix of `DimScenario[scenario_name]` × the five delta measures:
  `Scenario Delta Stockout Units`, `Scenario Delta Service Level`, `Scenario Delta Excess Days`,
  `Scenario Delta Fill Rate`, `Scenario Delta Avg Inventory Position`, each vs the baseline.
- **Conditional formatting:** colour+arrow on each delta (better vs worse vs "—"). Baseline row shows "—"
  (delta vs itself = 0 → show "—", not a misleading 0% improvement).

## Scenario outcome summary card (V7)
- **Visual:** multi-card/stat strip of the best-performing alternative scenario for the currently selected
  delta metric (e.g., "which scenario minimizes stockout units / maximizes service level"), with the runner-up.

## Cross-scenario series count (V8)
- **Visual:** `Series Count` per `DimScenario[scenario_name]` (all scenarios = 30,490 series; guard that a
  scenario never drops below that due to a valid run) as a sanity bar equal-height.

## Empty-state for the tradeoff table
- **Explicit:** a dedicated visual bound to `FactScenarioComparison` (0 rows) is placed with a "**No
  action-tradeoff table available for this scenario set (table empty). Comparing via FactScenarioResult
  deltas.**" caption. It must NOT silently render a blank/zero.

---

## Filters / interactions (P6)
- **Slicers:** scenario (multi-select), delta_metric, department, category, store.
- **Cross-filter:** choosing likely "interesting" filters (dept/store/category) recomputes V1–V6 slivers; a
  series selection is honoured for comparing a single series across scenarios.
- **Drill-downs:** dept→category→product.
- **Tooltips:** measure value + scenario + run + provenance (simulated).

## Empty / undefined states
- Comparison (baseline missing not possible) blank → "—".
- A scenario containing no rows for a category shows an empty bar (not zero).
- **Tradeoff table always shows the explicit "no tradeoff" empty-state.**

## Business interpretation
- V1–V5 show the direction of each alternative vs baseline (which improves and where).
- V6 delta table is the core planner steer: quantify the tradeoff numerically.
- V7 surfaces the winner for the selected objective.

## Accessibility / readability
- Delta arrows + colour + sign (never colour alone).
- Scenario names printed (not ids); baseline row distinct styling (hatched/grey) with "—" deltas.
- >=11pt labels; captions state what the "no tradeoff table" means.

---

## Validation (bound to this page)
- V1–V5 reconcile to `FactScenarioResult` grouped by `scenario_type`; each scenario = 30,490 series (maps to
  run ids 1–7, 30,490 baselines).
- V6 deltas vs baseline use the `Dimension[scenario_type]="baseline"` filter; undefined → "—".
- **P6 empty-state:** `fact_scenario_comparison = 0 rows` is handled as an explicit *no-tradeoff* empty state,
  never a fabricated comparison.
- Provenance simulated; no `fact_daily_sales`.