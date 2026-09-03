# Page 1 — Executive Overview

**Intent:** Control-tower snapshot: 30-second revenue/volume pulse, period growth, commercial
concentration (Pareto + dept/category/store), and first-pass inventory health flags. User reads this
first, then drills into a risk or scenario page.

**Primary sources:** `FactWeeklySales` (via `mv_weekly_sales`), `FactScenarioResult` (baseline + risk
runs), `DimWeek`, `DimProduct/DimCategory/DimDepartment/DimStore`, `DimScenario`, `DimScenarioRun`.

---

## Top-row KPI cards (V1–V4)
| # | Visual | Measure | Field(s) | Type |
|---|--------|---------|----------|------|
| V1 | Revenue card | `Total Revenue` | — | Card |
| V2 | Units card | `Total Units` | — | Card |
| V3 | Revenue growth | `Revenue WoW %` (toggle QoQ/YoY) | `DimWeek[period]` | Card with trend |
| V4 | Units growth | `Units WoW %` (same toggle) | — | Card with trend |

- Conditional formatting on V3/V4: positive = green ▲, negative = red ▼, undefined = "—".
- Period toggle (WoW/QoQ/YoY) is a page slicer bound to a `GrowthType` parameter (WoW/qoq/yoy).
- Business read: "Are we growing revenue faster than units? (price-led vs volume-led)."

## Revenue & Units trend (V5)
- **Visual:** Line & clustered column chart.
  - Columns: `Total Units` (left axis, weekly), line: `Total Revenue` (right axis), by `DimWeek[wm_yr_wk]`.
  - Trend line optional (computed measure not required — use visual trend if available).
- **Drill:** week → (day on `DimDate` only if a bounded forecast/inventory series selected, else disabled).
- **Tooltip:** units, revenue, weighted price, provenance (derived).

## Commercial concentration (V6–V9)
| # | Visual | Measure | Field | Type |
|---|--------|---------|-------|------|
| V6 | Revenue by department | `Total Revenue` | `DimDepartment[dept_name]` | Bar |
| V7 | Revenue by category | `Total Revenue` | `DimCategory[category_name]` | Donut |
| V8 | Revenue by state | `Total Revenue` | `DimStore[state_id]` | Map/bar |
| V9 | Product Pareto | `Product Revenue Share %` + `Cumulative Product Revenue Share %` | `DimProduct[product_id]` | Combo (Top-N bar + cumulative line) |

- **Top-N:** V9 `Top N = 10` (default), toggle 20/50 via `DimProduct` Top-N parameter.
- **Drill (V6):** dept → category → product. **Drill (V8):** state → store.
- **Tooltip:** share %, units, weighted price.

## Inventory health snapshot (V10–V13)
| # | Visual | Measure | Filter | Type |
|---|--------|---------|--------|------|
| V10 | Avg Days-of-Inventory | `Avg Days of Inventory` | baseline scenario (`DimScenario[scenario_type]="baseline"`) | Card |
| V11 | Avg Service Level | `Avg Service Level` | baseline | Card + gauge vs `assumption_set.service_level` |
| V12 | Stockout risk series | `Series at Risk Count` | stockout rank run (scenario_id of stockout_risk_rank) | Card |
| V13 | Excess risk series | `Series at Risk Count` | excess rank run | Card |

- **Pooling rule (locked):** V10–V13 read `FactScenarioResult` but **restricted to the specific run**
  (baseline for V10/V11; the two rank runs for V12/V13). A standalone `Scenario` slicer is NOT applied here
  (may be added as a separate comparison control on the page only if the author wants a live switch — default
  is baseline).
- **Conditional formatting V12/V13:** value = count in High/Critical; subtle emphasis to draw planner filters.

---

## Filters / interactions (P1)
- **Slicers:** period (week with growth toggle), department, category, store, state, product; Top-N (product
  Pareto).
- **Cross-filter:** selecting a department in V6 filters V7/V8/V9/V5 and the inventory snapshot; selecting a
  product in V9 filters inventory cards and (downstream) the risk pages.
- **Drill-downs:** state→store (V8); dept→category→product (V6); week→day only on bounded facts (V5 disabled
  for day if it would require a full 59M scan).
- **Tooltips:** provenance on every card/visual; units/price context on revenue visuals.

## Empty / undefined states
- If a period selection yields no weekly data (e.g., a calendar week with no sales), V5 shows the empty rows
  and trend cards show "—" — never a fabricated zero.
- If `Total Demand` is 0/blank, `Avg Service Level` and `Fill Rate` render "—".
- Snapshot cards show "—" when the baseline/rank-run filter context has no rows.

## Business interpretation
- Revenue vs units growth spread ⇒ price-vs-volume mix signal.
- Pareto concentration (V9) tells which products to attack first.
- Inventory snapshot (V10–V13) is a fast triage of where risk concentrates before diving into P4/P5/P6.

## Accessibility / readability
- KPI cards: value + unit label + provenance tag; growth arrows with colour + arrow glyph (not colour alone).
- Charts: contrasting line styles (dashed = cumulative), 11pt axis labels, title with "what to look for".
- Risk tier palette contrast-compliant.

---

## Validation (bound to this page)
- V1/V2 reconcile to `Total Revenue`/`Total Units` definitions (§A traceability) and to the locked
  `66,927,173` anchor.
- V9 uses `Product Revenue Share %`/`Cumulative Product Revenue Share %` (top-N, tie-break product id).
- V10–V13 provenance simulated and restricted to the correct run grain.
- No `fact_daily_sales` anywhere.