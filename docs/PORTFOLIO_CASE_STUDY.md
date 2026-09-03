# Supply Chain & Demand Intelligence Platform — Portfolio Case Study

A full end-to-end demand-forecasting and inventory-risk product built from a national retailer's daily sales data.

---

## 1. Business Problem

A multi-category grocery retailer holds **30,490 product-store combinations** across 3 states. Demand planning is hard because sales are **highly intermittent and volatile**: around **68% of product-store-day cells are zero**, and nearly every series is high-volatility. Two planning failures dominate:

- **Stockouts** — a hot item runs dry, losing the sale and customer trust.
- **Excess inventory** — cash is tied up in slow movers that don't turn.

Before this product, the planning team would chase symptoms. The question posed: **Can historical daily demand be turned into forecasts, inventory risk, and prioritised action so a team knows what will sell next, where the risk is, and what happens if policies change?**

The build answered it in a single, browser-based decision product.

---

## 2. Data Scale & Quality

- **Dataset:** the official M5 retail-forecasting dataset (a widely used forecasting benchmark).
- **Scale:** **59,181,090** observed daily sales records — the entire database is derived from these.
- **Series:** 30,490 product-store pairs (3,049 products × 10 stores), 3 categories, 7 departments.
- **Horizon:** observed **d_1–d_1941** (2011-01-29 → 2016-06-19, complete and continuous); **28-day** forecast window.
- **Quality:** 21/21 automated checks pass, 0 invalid records, 0 duplicates, 0 missing critical fields; only 1 benign warning (a single legitimate item priced above $100).
- **Integrity:** SHA-256 provenance manifest; raw files preserved unchanged.

---

## 3. Solution Architecture

```
SOURCE (M5) → VALIDATION → ETL → PostgreSQL warehouse
   → SQL analytics → demand analysis → forecasting
   → inventory simulation → scenario engine
   → FastAPI web product (static SPA) → decision-makers
```

A layered pipeline where every layer depends on the validated output of the one before it. The warehouse is PostgreSQL 17; the web layer is read-only and never scans the 59M-row fact table wholesale — every endpoint is bounded, paginated, and filterable. Data provenance is tracked precisely (Observed / Derived / Simulated) at every step.

---

## 4. Demand Intelligence

For every product-store series the platform computed and stored:

- **Trend** — direction and normalised effect (never manufactured on short/zero series).
- **Volatility** — coefficient of variation on daily units.
- **Growth** — recent vs prior 4-week change, with a disciplined zero-denominator guard.
- **Seasonality** — month-of-year and day-of-week indices, only where genuinely meaningful.
- **Segmentation & risk matrix** — a **volume × volatility** matrix (Critical / High / Moderate / Low) to guide where to pay attention first.

Outputs: 30,490 analysed series, 359,181 seasonality rows, reproducible threshold rules. This layer turns "which series are risky?" into an answerable, filterable question.

---

## 5. Forecasting

The forecast layer is deliberately **honest about evaluation**:

- **Chronological splits only** (train to d_1913, validate d_1914–d_1941) — no random split, no leakage.
- **Baselines across all 30,490 series** — naive, seasonal-naive, moving average, weighted moving average. Weighted MA is the strongest aggregate baseline (WMAE **4.34**).
- **Advanced models, bounded** — ETS/Holt-Winters and SARIMA are fitted on a **top-64 high-volume pilot subset** (never 30,490 uncontrolled fits) and adopted per-series only when they beat the best baseline by a margin (≥1% WMAE).
- On the pilot subset, **ETS ≈ 12.1% better** and **SARIMA ≈ 11.2%** than the pilot best baseline.
- Every series gets a 28-day forecast with ~95% prediction intervals.

Outputs: **853,720** forecast rows, 6-model registry, per-series champion selection (Naive is the most frequent per-series winner — a true, non-obvious finding for sparse demand), **122,088** evaluation rows.

---

## 6. Inventory Simulation

Because the retailer's actual inventory records are not part of the public dataset, inventory is **modelled** from forecasts — and labelled simulated throughout:

- A fixed **(s,Q) reorder policy** with safety stock, **7-day lead time**, and **95% target service level**.
- A day-by-day state machine per series: orders, arrivals, demand, backorders, stockouts, excess, service level, fill rate.
- Precedence is reproducible via a persisted **assumption set**.

Outputs: **853,720** simulated day-rows across all series, **0 contract violations** (the `projected_stockout` flag is always consistent with stored units at DB precision), pilot mean achieved service level **0.9336** vs **0.95** target — reported honestly as a real gap driven by forecast variability, not hidden.

---

## 7. Scenario Intelligence

The simulation is re-run under controlled changes to quantify downstream impact:

| Scenario | Type |
|---|---|
| Baseline | baseline |
| +20% demand shock | demand shock |
| +2 days lead time | lead-time change |
| 99% service-level target | service-level change |
| Alternate reorder policy | reorder policy |
| Stockout-risk prioritisation / Excess-risk prioritisation | risk ranking |

Outputs: **7 scenarios × 30,490 series = 213,430** simulated result rows, plus a ranked risk worklist. An action-tradeoff comparison and replenishment-recommendation layer are intentionally deferred (empty state, never fabricated).

---

## 8. Web Product

A single-page decision dashboard with **six views** — Executive, Demand Intelligence, Forecasting, Inventory, Scenario Intelligence, and Operational Risk/Priority:

- **Live forecasts & drill-downs** to any series (28 points / days, bounded).
- **Server-side filtering, pagination, and drill-downs** — nothing bulk-loaded into the browser.
- **Provenance badges** (Observed / Derived / Simulated) on every figure.
- **Ranked risk worklist** with a drill-down evidence panel, keyboard-accessible (Enter opens details).
- **Responsive** to mobile; consistent locked 5-colour palette; accessible by design.
- Explicit empty/error states throughout.

**178 web/API tests** validate shell, pages, API contracts, filters, pagination, drill-downs, accessibility, responsive layout, and palette compliance.

---

## 9. Validation & Reliability

- **653 automated tests passing** across the full pipeline (data 19, warehouse/schema, demand, forecasting 98, inventory 109, scenario 94, web/API 178).
- Chronological, leakage-free forecast validation.
- Bounded drivers — none of the production runs scan the 59M-row fact table character-by-character; all use bounded, resumable, FK-safe writes.
- Read-only web data layer; no secrets in source; environment-driven configuration.
- Full production web validation run against real database-backed data.

---

## 10. Results / Evidence

| Result | Evidence |
|---|---|
| Strongest aggregate baseline | Weighted MA, WMAE **4.34** across all 30,490 series |
| Statistical uplift (pilot) | ETS **≈12.1%**, SARIMA **≈11.2%** vs pilot best baseline |
| Forecast coverage | 30,490 series × 28 days = **853,720** rows, intervals populated |
| Inventory coverage | 30,490 series × 28 days = **853,720** simulated rows, 0 violations |
| Scenario coverage | 7 scenarios × 30,490 = **213,430** simulated rows |
| Risk coverage | **30,490** deterministically ranked series |
| Test evidence | **653 tests passing** |

Every number traces to `reports/PHASE_*_REPORT.md` and the live API. No financial savings or business-impact figure is invented — the honest, measured outputs are listed above.

---

## 11. Limitations

- **Inventories are simulated**, not observed — there is no real inventory in the source dataset.
- **Forecast edge is thin by design** — daily grocery demand is sparse and volatile; baselines already perform well and advanced models are retained only where they genuinely help.
- **Achieved service level trails target** (0.9336 vs 0.95) because of real forecast variability; reported transparently.
- **Decision-recommendation layer deferred** — replenishment recommendations are intentionally not populated.
- **Fixed policy inputs** (lead time, (s,Q)) are assumption-set driven and reproducible.

---

## 12. Technologies

- **Warehouse:** PostgreSQL 17
- **Data engineering & analytics:** Python (pandas, numpy), psycopg2, chunked ETL
- **Forecasting/maths:** statsmodels, scikit-learn, scipy
- **Web/API:** FastAPI + uvicorn, vanilla HTML/CSS/JS static SPA
- **Testing:** pytest (653 tests)
- **Deployment:** Docker / docker-compose

---

## 13. Live Demo / Repository

- **Source layout & how to run:** [`README.md`](../README.md)
- **Deployment:** [`DEPLOYMENT.md`](../DEPLOYMENT.md)
- **Architecture docs:** [`docs/architecture.md`](../docs/architecture.md)
- **Design system:** [`docs/design_system.md`](../docs/design_system.md)
- **Screenshots:** `step5-*.png`, `step6-*.png`, `step7-*.png`

_Demo/placeholder: this case study accompanies a local, runnable repository. Live-host URL (if/when deployed) can be added here without changing the analysis._