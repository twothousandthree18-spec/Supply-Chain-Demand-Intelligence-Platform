# Page 7 — Prioritized Operational Insights

**Intent:** Turn the risk and scenario outputs into a ranked, action-oriented worklist. The planner filters by
risk tier and objective (stockout vs excess vs scenario delta), picks an insight, then cross-dives into P4/P5/P6
for the responsible product/store. All content **simulated** (rank runs + scenario results).

**Primary sources:** `FactScenarioResult` (rank runs + scenario set), `DimProduct/DimStore/DimCategory/
DimDepartment`, `DimScenarioRun`.

---

## Prioritized worklist (V1)
- **Visual:** table of prioritized insights (rows) with fields:
  - `product_label`, `store_id`, `dept_name`
  - `risk_type` (stockout / excess)
  - `risk_tier` (chip), `risk_score`, `risk_rank`
  - `Total Stockout Units` / `Total Stockout Days` (for stockout rows) OR `Total Excess Units` / `Total Excess
    Days` (for excess rows)
  - `Avg Service Level`, `Avg Days of Inventory` (cross context to the inventory illumination)
  - sort key = `risk_rank ASC` (rank score 위) — the worklist is rank-ordered; Top-N default 30, toggle 50/100.
- **Conditional formatting:** `risk_tier` chip colours; `risk_score` colour ramp; bigger rank → hotter.

## Objective switcher (V2)
- **Visual:** segmented single/donut to choose the objective for the worklist: **Stockout** (rank run stockout)
  vs **Excess** (rank run excess) vs **Scenario-based** (pick a delta_metric; rows = series ordered by
  `Scenario Delta` for the Best/Worst). Drives V1 rows.

## Insight highlights (V3–V6)
| # | Visual | Measure | Note |
|---|--------|---------|------|
| V3 | Top stockout series | `Stockout Risk Rank` (top 5) | mini table/chips |
| V4 | Top excess series | `Excess Risk Rank` (top 5) | mini table/chips |
| V5 | Risk-tier balance | `Series at Risk Count` by `risk_tier` (both risk kinds) | stacked bar |
| V6 | Best scenario for objective | `Scenario Delta ...` best | card (ties to P6 V7) |

## Series detail (V7)
- **Visual:** when a worklist row is selected, show `Avg Service Level`, `Fill Rate`, `Avg Days of Inventory`,
  `Avg Inventory Position`, and the `risk_components` (jsonb text → driver chips).

---

## Filters / interactions (P7)
- **Slicers:** risk_tier, department, category, store, `risk_score_threshold`, objective (V2), sort/Top-N.
- **Cross-filter:** row in V1 → V7 detail and cross-page dive (P4 horizon, P5 rank, P6 scenario for that series).
- **Drill-downs:** dept→category→product; store→state.
- **Tooltips:** score, tier, rank, driver components.

## Empty / undefined states
- A `risk_type`/tier selection with zero series shows an empty worklist message ("no series meet this tier").
- A scored series with no `risk_components` shows "no feature drivers".
- Undefined metric cells → "—".

## Business interpretation
- The worklist is THE leave-with plan: next actions are the top rows when the planner trusts risk rank.
- Objective switch (V2) lets the planner optimize for stockout avoidance vs inventory-carry minimization vs a
  particular scenario objective.

## Accessibility / readability
- Ranks shown numerically (unique per run); tier chips colour+text; row captions for the worklist with clear
  headers; >=11pt table/axis text when possible.

---

## Validation (bound to this page)
- `risk_rank` per run unique 1..30,490; `risk_tier` ∈ {Critical, High, Medium, Low}; Top-N native rank-ordered.
- Worklist uses `FactScenarioResult` restricted to the correct rank run or scenario set; never crosses the
  pilot/support boundary.
- Undefined metrics render "—"; empty tier shows explicit empty message.
- Provenance simulated; no `fact_daily_sales`; no web app.