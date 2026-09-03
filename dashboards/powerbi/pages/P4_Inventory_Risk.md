# Page 4 — Inventory Risk

**Intent:** Inspect simulated inventory posture per series over the 28-day horizon — service, fill, days on
hand, position — and spot where stock runs thin (or piles up). Read the inventory simulation (28-day bounded).

**Primary sources:** `FactInventorySimulation` (853,720 = 30,490×28), `DimProduct/DimStore/DimDepartment/
DimCategory`, `DimDate`, `DimAssumptionSet`.

**Provenance:** simulated (all content on this page).

---

## Horizon-position cards (V1–V4)
| # | Visual | Measure | Type |
|---|--------|---------|------|
| V1 | Avg Service Level (horizon) | `Avg Service Level` | Card |
| V2 | Fill Rate (horizon) | `Fill Rate` | Card |
| V3 | Avg Days-of-Inventory | `Avg Days of Inventory` | Card |
| V4 | Avg Inventory Position | `Avg Inventory Position` | Card |

- **Scope:** default over the selected `assumption_set` + `DimDate` horizon (bounded 1942..1969). Cards are
  **non**-additive measures; never summed.
- **Undefined:** BLANK → "—".

## Service level distribution & trend (V5–V8)
| # | Visual | Measure/Field | Type |
|---|--------|------------|------|
| V5 | Service-level histogram | `Series Count` by `service_level` bin | Histogram |
| V6 | Avg service level by day | `Avg Service Level` by `DimDate[calendar_date]` (28-day) | Line |
| V7 | Avg inventory position by day | `Avg Inventory Position` by `DimDate[calendar_date]` | Line |
| V8 | Days-of-inventory by dept | `Avg Days of Inventory` by `DimDepartment[dept_name]` | Bar |

- **Day-grain rule:** V6/V7 read `FactInventorySimulation` (28-day horizon only); never the observed daily fact.

## Service/fill gap (V9)
- **Visual:** bar of `Fill Service Gap` by `DimStore[store_id]` (or category) — the gap between achieved
  service/fill and the assumption-set target.

## Assumption-set sensitivity (V10)
- **Visual:** `Avg Service Level` and `Avg Days of Inventory` by `DimAssumptionSet[assumption_set_name]`
  (a small set of runs) — shows how service vs days-of-inventory trade against assumptions.

---

## Filters / interactions (P4)
- **Slicers:** assumption_set, `DimDate` (28-day), department, category, store, product.
- **Cross-filter:** a series selection cross-filters V6/V7 (vertical reading) and feeds P5 stockout/excess view.
- **Drill-downs:** dept→category→product; product→store; day within horizon.
- **Tooltips:** service level, fill rate, days-of-inventory, position, assumption set, provenance (simulated).

## Empty / undefined states
- Service/fill undefined when demand is zero → "—".
- Unselected series → histogram all-zero view is avoided (show empty), a poster prompt for series selection.
- V10: an assumption set with no rows shows an empty bar label (not zero).

## Business interpretation
- V5 sd of service tells how many series are far below target.
- V6/V7 trend shows whether inventory is bleeding down over the horizon (stockout risk rising).
- V8 varies by department — where capacity/days-on-hand is thinnest.
- V9 gap quantifies the miss vs the assumption target at a glance.

## Accessibility / readability
- Histograms with explicit bin labels; line legends placed for contrast on both light background variants.
- Tier/relevance palette only for differentiating categories; numbers always labelled.
- Data label + caption; no colour-only encoding.

---

## Validation (bound to this page)
- V1–V4 read `FactInventorySimulation` reconciled to the 853,720 grain; non-additive shown as measures.
- V6/V7 day-grain visuals are bounded to 28-day horizon (date span 1942..1969).
- Provenance simulated; no `fact_daily_sales`.