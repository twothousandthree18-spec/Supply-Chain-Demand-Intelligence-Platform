# Page 5 — Stockout & Excess Risk

**Intent:** Rank the 30,490 series by stockout risk and by excess (overstock) risk using the scenario
rank runs (`risk_rank` 1..30,490, unique per run, no ties — verified). Identify the riskiest series, their
colour-coded tier, and drill into a specific product/store.

**Primary sources:** `FactScenarioResult` restricted to the two rank runs (stockout-rank run and excess-rank
run), `DimScenarioRun`, `DimScenario`, `DimModel` (accidentally not present, not needed), `DimProduct/DimStore/
DimDepartment/DimCategory`.

**Provenance:** simulated. Risk magnitudes are only meaningful on these rank runs; contrast by scenario.

---

## Risk tier cards (V1–V5)
| # | Visual | Measure | Notes |
|---|--------|---------|-------|
| V1 | Series at risk (stockout) | `Series at Risk Count` | High+Critical on stockout rank |
| V2 | Series at risk (excess) | `Series at Risk Count` | High+Critical on excess rank |
| V3 | Avg stockout risk score | `Stockout Risk Score` | over rank run |
| V4 | Avg excess risk score | `Excess Risk Score` | over rank run |
| V5 | Tier distribution | `Series Count` by `risk_tier` | stacked bar (both runs) |

- **Tier labels/colours (locked):** Critical dark red, High red-orange, Medium amber, Low green.

## Risk rank tables & ranking (V6–V9)
| # | Visual | Measure/Field | Type |
|---|--------|--------------|------|
| V6 | Stockout rank leaderboard | `risk_rank` (asc), `Total Stockout Units`, `Total Stockout Days`, `risk_score`, `risk_tier` | Table (Top-N 20/50) |
| V7 | Excess rank leaderboard | `risk_rank` (asc), `Total Excess Units`, `Total Excess Days`, `risk_score`, `risk_tier` | Table (Top-N) |
| V8 | Stockout risk by state | `Stockout Risk Score` by `DimStore[state_id]` | Bar |
| V9 | Excess risk by dept | `Excess Risk Rank` (avg) by `DimDepartment[dept_name]` | Bar |

- **Top-N (V6/V7):** default 20, toggle 50/100; uses native `risk_rank` (1 = highest risk) — lowest rank first, no re-rank.
- **Conditional formatting:** V6/V7 risk_tier cell + `risk_score` colour ramp; V8/V9 bars coloured by avg tier.

## Risk tier summary (V10)
- **Visual:** donut/sunburst of `Series Count` by `risk_tier` × `risk_type` (stockout/excess). Highlights the
  Critical shares separately for the two risk kinds.

## Risk driver components (V11)
- **Visual:** selected series detail — `risk_components` (jsonb text) rendered as a small table of contributing
  components (per scenario/risk_component) on series selection.

---

## Filters / interactions (P5)
- **Slicers:** risk_type (stockout/excess), risk_tier, Top-N, department, category, store, state.
- **Cross-filter:** a row selection in V6 dirills V11 (driver components) and sends the series into P4 horizon /
  P6 scenario (cross-page by series identity).
- **Drill-downs:** dept→category→product; store→state.
- **Tooltips:** score, tier, rank, component labels.

## Empty / undefined states
- Rows with no risk component are filtered out (risk_components empty) but the series still counts in tier if
  it has a `risk_score`; an empty-component selection shows "no components" message.
- A tier with zero series shows an empty label (not zero).

## Business interpretation
- Rank leaderboards (V6/V7) define the operational worklist: the top-N by stockout/excess risk.
- State/dept bars (V8/V9) show where the systemic risk concentrates.
- V11 explains WHY a series is risky (which component dominated).

## Accessibility / readability
- Rank tables list `risk_rank` explicitly (unique 1..30,490) for traceability; leaderboard shows rank number
  + score + tier chip (colour + text).
- Tier chips use colour + text label (colour never sole discriminator).
- Data captions and >=11pt on titles/labels.

---

## Validation (bound to this page)
- V6/V7 `risk_rank` per run is unique 1..30,490 (no ties — verified locked data).
- Risk tier values are within {Critical, High, Medium, Low}.
- V1/V2 `Series at Risk Count` = High+Critical tallies over the appropriate rank run.
- Provenance simulated; no `fact_daily_sales`.