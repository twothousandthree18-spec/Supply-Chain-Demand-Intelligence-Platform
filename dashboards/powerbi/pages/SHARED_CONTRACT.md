# Phase 5 — Shared Page Build Contract (all 7 pages)

Validates every page against the locked KPI/source/interaction contract. These rules are
**global and mandatory** — each page spec (P1..P7) may add page-specific requirements but never
overrides these.

## 1. Provenance rule (global)
- Every visual that reads a **derived** or **simulated** metric must be **labeled** with its
  provenance (`Provenance Label` measure read from the table's `data_provenance`).
- **Observed** content appears only via `FactWeeklySales`/weekly anchor (derived) — never a direct
  `fact_daily_sales` surface.
- P3 (forecast) provenance = **derived**; P4/P5/P6/P7 = **simulated**. (Step 1 verified.)

## 2. No-fact-daily-sales rule (global)
- No page may reference `fact_daily_sales`. The only daily-grain visuals are bound to
  `DimDate` + the **bounded 28-day horizon** tables (`FactForecast`, `FactInventorySimulation`) or the
  monthly `FactDemandSeasonality`. Day-grain access is always pre-filtered (no unbounded scan).

## 3. Grain & aggregation rule (global)
- **Additive** measures (Total Revenue/Units, Stockout/Excess Days/Units, Total Demand,
  Replenishment) sum over any product/store subset.
- **Non-additive** measures (Weighted Price, Avg Service Level, Fill Rate, Avg Days-of-Inventory,
  Avg Inventory Position, WMAE/WRMSE/Bias, risk scores) are shown as **measure values**, never summed
  as raw and never misinterpreted as additive.

## 4. Undefined-metric rule (global)
- Any measure that undefined (no data in context, zero denominator, BLANK) displays **"—"**
  (`Display Dash`). Never a fabricated `0`.

## 5. Top-N rule (global)
- Top-N = highest measure value, ties broken by `product_surr_id ASC` (then `store_surr_id ASC`).
- Where a rank is native (`risk_rank` 1..30,490) use it directly (no re-rank).

## 6. Interaction rule (global)
- Cross-filtering is **single-direction downstream** (dim → fact). Page-level visuals cross-filter
  within the page; a selected series cross-filters P4↔P5↔P6 as specified per page.
- Drill paths: state→store; department→category→product; period→week→day (day only on bounded facts).
- Slicers affect all visuals on the page (not page-filtered out of existence).

## 7. Accessibility / readability (global)
- Text ≥ 11pt on titles and axis labels; ≥ 10pt legibility minimum for dense tables.
- Colour is **not the only discriminator** — pair contrast with data labels, line styles, or icons.
- Risk tier colours use the fixed palette (Critical dark red, High red-orange, Medium amber, Low green).
- Tables expose the underlying values with unit labels and provenance tag.
- Every page has a data-title + a one-line "what to look for" business caption.

## 8. Empty/undefined page states (global)
- A page with a filter returning no data shows an informative empty card; the literal "—" for metrics;
  never a silent blank that reads as zero.