# Supply Chain & Demand Intelligence Platform

> Demand Forecasting · Inventory Risk · Operational Decision Intelligence

A decision-intelligence web product that answers one business question:

> **Can you use a retailer's historical daily demand to forecast what will sell next, spot inventory risk before it hurts, and guide better replenishment decisions?**

The platform takes **59.18M logged daily sales observations** across a national grocery retailer's **30,490 product-store combinations**, turns them into forecasts, simulates inventory behavior to expose stockout and excess risk, ranks where to act first, and presents it all in a single browser-based decision dashboard.

**Built from scratch end to end** — raw data → warehouse → analytics → forecasting → inventory simulation → scenario planning → live web product — with every number traceable to source. This is a demonstration of the full analytical and engineering workflow a data team would run for a supply-chain organisation.

---

## The business problem

A large multi-category retailer faces a classic demand-planning dilemma:

- **Demand is highly intermittent and volatile** — ~68% of product-store-day cells are zero; nearly every series is high-volatility.
- **Forecasting is hard**: a naive day-ahead guess is a strong baseline, and the edge is thin.
- **Inventory risk is asymmetric** — running out (stockout) loses sales and trust; over-ordering (excess) ties up cash in slow movers.
- **Priorities are unclear** — with tens of thousands of product-store combinations, where do you focus first?

The platform answers this concretely, so a planning team can see **what will sell, where the risk is, and what happens if policies change** — in one place.

---

## Dataset scale

Worked from the official **M5 Walmart retail-forecasting dataset** (a widely used forecasting benchmark).

| Scope | Value |
|---|---|
| Observed daily sales records | **59,181,090** |
| Product-store demand series | **30,490** (3,049 products × 10 stores) |
| Observed horizon | **d_1 – d_1941** (2011-01-29 → 2016-06-19, continuous) |
| Forecast / simulation horizon | **28 days** (d_1942 – d_1969) |
| Raw source size | ~424 MB, 0 failed quality checks (21 PASS / 0 FAIL / 1 benign WARN) |
| Product hierarchy | 3 categories · 7 departments (FOODS / HOBBIES / HOUSEHOLD) |
| Geography | 10 stores · 3 states (CA, TX, WI) |

---

## What the product does

A browser-based decision intelligence dashboard with **six linked views**, each answering a planning question:

1. **Executive** — headline KPIs, sales contribution, top signals (what matters right now).
2. **Demand Intelligence** — trend, volatility, growth, seasonality, and a volume × volatility risk matrix for every series, with filters and drill-downs.
3. **Forecasting** — 28-day forecasts with ~95% prediction intervals, model accuracy, and drift-down to any series.
4. **Inventory** — simulated service level, fill rate, stockout days, excess days, and reorder policy across all series and per series.
5. **Scenario Intelligence** — what-if runs (demand shock, lead-time change, service-level target, reorder-policy change) compared against a baseline.
6. **Operational Risk / Priority** — a ranked worklist of stockout/excess risk across all 30,490 series with a drill-down evidence panel.

Every figure is tagged with its provenance — **Observed / Derived / Simulated** — so users always know what is real data, what is computed, and what is simulated.

---

## How it works

### Forecasting
Daily demand is forecast for all 30,490 series over a 28-day horizon using chronological (never random) train/validate splits. Four transparent baselines run across every series; **ETS/Holt-Winters and SARIMA** are fitted on a bounded high-volume pilot subset and adopted per-series only when they beat the best baseline by a margin. The most-frequent winning model is the champion baseline.

### Inventory simulation
Because the retailer's real inventory records were not available, inventory is **modelled** from the demand forecasts: a fixed (s,Q) reorder policy with safety stock, a 7-day lead time, and a 95% target service level. The simulation replays each series day-by-day over the horizon and reports achieved service level, fill rate, stockouts, and excess. These are explicitly **simulated** — never presented as observed events.

### Scenario analysis
The same simulation is re-run under controlled changes (e.g. +20% demand, +2 days lead time, 99% service target, alternate reorder policy) to quantify the downstream effect on stockouts, service, fill rate, and inventory — all with clearly labelled simulated provenance.

---

## Key measured outputs

Real, produced-by-this-pipeline figures (not aspirational):

| Output | Measured result |
|---|---|
| Baseline comparison (full 30,490-series holdout) | best aggregate baseline = **Weighted MA**, WMAE **4.34** |
| Statistical models vs pilot subset baseline | **ETS ≈ 12.1% better WMAE**, **SARIMA ≈ 11.2%** on the top-64 pilot |
| Forecast outlets | **853,720** forecast rows (30,490 × 28 days), 0 negatives, all PI bounds populated |
| Model registry | 6 models; per-series champion selection across all 30,490 series |
| Inventory simulation | **853,720** simulated day-rows, 0 contract violations, 0.998 mean fill rate on pilot |
| Achieved vs target service level (pilot) | **0.9336** mean achieved vs **0.95** target — the honest gap from forecast variability |
| Scenario runs | 7 scenarios × 30,490 series = **213,430** simulated result rows |
| Risk worklist | **30,490** deterministically ranked series (native risk rank 1..30,490) |

All figures can be traced to `reports/PHASE_*_REPORT.md` and the live API.

---

## Validation & testing evidence

- **653 automated tests pass** across data quality, warehouse/schema, demand analytics, forecasting (98), inventory (109), scenario (94), and web/API (178).
- Data pipeline: 21/21 effective quality checks, 19/19 data tests.
- Full database-backed web regression and live API validation against real data.
- Read-only web layer: no bulk scan of the 59M-row fact table; every endpoint is paginated/filtered/bounded.

---

## Architecture overview

```
SOURCE (M5, 59.18M rows)
   → VALIDATION → ETL → PostgreSQL warehouse (PostgreSQL 17)
   → SQL analytics → demand analysis → forecasting
   → inventory simulation → scenario engine
   → decision web product (FastAPI + static SPA) → consumer
```

The analytical outputs live in a Postgres warehouse; a FastAPI service serves a single-page product that never reads raw 59M-row demand in full — it queries bounded, paginated endpoints.

## Technology stack

| Layer | Technology |
|---|---|
| Data warehouse | PostgreSQL 17 |
| Data engineering | Python (pandas, numpy), psycopg2, chunked ETL |
| Analytics & forecasting | statsmodels (ETS/SARIMA), scikit-learn, scipy |
| Scenario / inventory engine | Python (pure, formula-locked, deterministic) |
| Web / API | FastAPI + uvicorn, static HTML/CSS/JS (Vanilla) |
| Testing | pytest (653 tests) |
| Deployment | Docker / docker-compose (PostgreSQL + app) |

---

## Data provenance distinction

The project is disciplined about the difference between fact and model:

- **Observed** — the 59.18M real daily sales records (never altered, never read wholesale by the web layer).
- **Derived** — computed demand analytics and forecasts, reproducible from a single source of truth.
- **Simulated** — inventory behavior and scenario outcomes, clearly labelled and never presented as real events.

---

## Important limitations

- **Inventories are simulated** — the source dataset contains no real inventory records; stockouts, lead times, and orders are modelled, not observed.
- **Statistical forecast edge is thin** by design: daily grocery demand is sparse and volatile; a weighted moving average is already a strong baseline, and advanced models earn their place only on the highest-volume series.
- **Achieved service level trails the 95% target** (pilot 0.9336) because of genuine forecast variability — the dashboard reports this honestly rather than hiding it.
- **Decision/recommendation layer not started** — `fact_replenishment_recommendation` is intentionally empty; no recommendation is fabricated.
- **Fixed policy inputs** (7-day lead time, (s,Q) policy) are assumption-set controlled and reproducible.

---

## How to run locally

Prerequisites: **Python 3.14**, **PostgreSQL 17**, and the populated `supply_chain_intelligence` database (the Phase 1–5 pipeline output).

```bash
# 1. Install dependencies
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows
# .venv/bin/pip install -r requirements.txt           # Linux/macOS

# 2. Configure PostgreSQL (env-driven; see .env.example)
#    PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD

# 3. Start the web product (static SPA + API)
.venv\Scripts\python.exe -m uvicorn src.web.main:app --host 0.0.0.0 --port 8000

# open http://localhost:8000    health: http://localhost:8000/healthz
```

Repository workflows (data acquisition → ETL → analytics → forecasting → inventory → scenarios) are documented in `reports/PHASE_*_REPORT.md` and `docs/`.

## Deployment

The app is a stateless FastAPI service + static assets; PostgreSQL is the only external dependency. See **[`DEPLOYMENT.md`](DEPLOYMENT.md)** for environment variables, the production start command, the provided **Dockerfile** and **docker-compose.yml**, and reverse-proxy notes.

## Portfolio artefacts

| Artefact | Path |
|---|---|
| Portfolio case study | [`docs/PORTFOLIO_CASE_STUDY.md`](docs/PORTFOLIO_CASE_STUDY.md) |
| Final project summary | [`reports/FINAL_PROJECT_SUMMARY.md`](reports/FINAL_PROJECT_SUMMARY.md) |
| Architecture (Phases 0–6) | [`docs/architecture.md`](docs/architecture.md) |
| Phase reports | [`reports/PHASE_*_REPORT.md`](reports/) |
| Design system (locked 5-colour palette) | [`docs/design_system.md`](docs/design_system.md) |
| Screenshots | `step5-*.png`, `step6-*.png`, `step7-*.png` |

*This project is a Data Analyst / BI Analyst portfolio demonstration. Simulated figures are always labelled as such and are never presented as real company data.*