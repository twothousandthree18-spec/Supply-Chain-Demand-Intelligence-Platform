# Supply Chain & Demand Intelligence Platform
## Architecture Document

**Subtitle:** Demand Forecasting, Inventory Risk & Operational Decision Intelligence

**Version:** 1.0 (Phase 0 — Design)
**Status:** Implementation-ready architecture. Nothing in this document has been built or populated yet.

---

## 1. Primary Business Question

> Can a company use historical demand data to forecast future demand, identify inventory risks, and make better replenishment decisions?

This single question drives every downstream decision: what data we need, how we model demand, how we simulate inventory, and how we translate evidence into actionable recommendations.

---

## 2. End-to-End Pipeline

```
SOURCE DATA
    │
    ▼
DATA VALIDATION
    │
    ▼
PYTHON ETL
    │
    ▼
POSTGRESQL
    │
    ▼
SQL ANALYTICAL LAYER
    │
    ▼
PYTHON ANALYTICS
    │
    ▼
FORECASTING ENGINE
    │
    ▼
INVENTORY SIMULATION
    │
    ▼
SCENARIO ENGINE
    │
    ▼
DECISION ENGINE
    │
    ▼
POWER BI / WEB PRESENTATION
```

The pipeline is strictly layered. Each layer consumes the outputs of the layer above it and produces inputs for the layer below it. No layer may skip a dependency (e.g., forecasting never consumes raw files directly; it consumes curated, validated data from PostgreSQL).

---

## 3. Layer-by-Layer Specification

For each layer we document: **purpose, inputs, outputs, technology, dependencies, and expected responsibility.**

### 3.1 SOURCE DATA
- **Purpose:** Acquire and hold the official external dataset untouched.
- **Inputs:** The M5 Walmart retail forecasting dataset (public Kaggle competition data).
- **Outputs:** Immutable raw files (CSV) stored under `data/raw/` with checksums.
- **Technology:** CSV files + SHA-256 checksums recorded in a manifest.
- **Dependencies:** None (external source).
- **Responsibility:** Preserve the original data exactly; never modify in place.

### 3.2 DATA VALIDATION
- **Purpose:** Prove the raw data is usable before it enters the warehouse.
- **Inputs:** Raw source files.
- **Outputs:** A data quality report and pass/fail gate (recorded in `data_quality_results`).
- **Checks:** schema conformity, duplicate detection, nulls, invalid codes/relationships, calendar/date continuity, and value-range sanity.
- **Technology:** Python (pandas) + pytest-style checks; results written to PostgreSQL metadata.
- **Dependencies:** SOURCE DATA.
- **Responsibility:** Block downstream load if critical rules fail; document all findings.

### 3.3 PYTHON ETL
- **Purpose:** Transform raw records into a normalized, typed, validated warehouse model.
- **Inputs:** Validated raw source files.
- **Outputs:** Populated dimension and fact tables in PostgreSQL.
- **Technology:** Python (pandas), SQLAlchemy/psycopg for connection, SQL DDL for schema.
- **Dependencies:** DATA VALIDATION, POSTGRESQL schema.
- **Responsibility:** Idempotent loads, auditable via `etl_run_log`. Never loads unvalidated data.

### 3.4 POSTGRESQL
- **Purpose:** The single source of truth for all stored data.
- **Inputs:** ETL output (dimensions + fact tables), plus SQL analytical views.
- **Outputs:** Curated tables and analysis-ready views.
- **Technology:** PostgreSQL 17. Referential constraints, indexes, and updated-at tracking.
- **Dependencies:** PYTHON ETL.
- **Responsibility:** Enforce integrity; version schema via DDL files under `sql/`.

### 3.5 SQL ANALYTICAL LAYER
- **Purpose:** Compute core business KPIs and expose analysis-ready views.
- **Inputs:** Warehouse fact + dimension tables.
- **Outputs:** KPI views (revenue, units, price, growth, contribution, demand stats, inventory position).
- **Technology:** SQL (views, materialized views where needed), files under `sql/analytics/`.
- **Dependencies:** POSTGRESQL.
- **Responsibility:** Single, tested definition of every KPI. Correctness is verified by SQL tests.

### 3.6 PYTHON ANALYTICS
- **Purpose:** Deeper analysis beyond what SQL expresses cleanly (volatility, demand patterns, exploratory statistics).
- **Inputs:** Analytical views.
- **Outputs:** Derived metrics and analytical datasets used by forecasting/inventory/scenario layers.
- **Technology:** Python (pandas, numpy).
- **Dependencies:** SQL ANALYTICAL LAYER.
- **Responsibility:** Reproducible computations; every metric defined and tested.

### 3.7 FORECASTING ENGINE
- **Purpose:** Produce validated, time-series-correct forecasts for product/store demand.
- **Inputs:** Curated historical demand series (observed data only).
- **Outputs:** Forecasts (`fact_forecast`) and forecast evaluation metrics (`fact_forecast_evaluation`).
- **Technology:** Python; baseline/statistical/ML models as justified (see Forecasting Architecture).
- **Dependencies:** PYTHON ANALYTICS / observed historical data.
- **Responsibility:** Chronological-only validation; no leakage; reproducible; evaluated honestly.

### 3.8 INVENTORY SIMULATION
- **Purpose:** Model inventory positions over time under stated assumptions.
- **Inputs:** Forecasts + configurable operational assumptions (lead time, service level, policies).
- **Outputs:** Simulated inventory series, projected stockouts, excess inventory (`fact_inventory_simulation`).
- **Technology:** Python discrete-event/rolling simulation.
- **Dependencies:** FORECASTING ENGINE + assumption config.
- **Responsibility:** Every assumption explicit and configurable; clearly tagged as simulated.

### 3.9 SCENARIO ENGINE
- **Purpose:** Re-run the simulation/forecast under alternative business conditions.
- **Inputs:** Baseline forecasts + scenario deltas (demand shock, lead-time change, promotion uplift).
- **Outputs:** Scenario comparison outputs and affected KPI deltas.
- **Technology:** Python (parameterized engine).
- **Dependencies:** INVENTORY SIMULATION + FORECASTING.
- **Responsibility:** Isolated, comparable scenario results; explicit assumptions.

### 3.10 DECISION ENGINE
- **Purpose:** Convert evidence into traceable operational recommendations.
- **Inputs:** Forecasts, inventory simulation, scenario outputs.
- **Outputs:** Recommendations (REORDER / MONITOR / REDUCE INVENTORY / HIGH STOCKOUT RISK / EXCESS INVENTORY / NO ACTION REQUIRED).
- **Technology:** Python rules engine; every rule traceable to data.
- **Dependencies:** INVENTORY SIMULATION + SCENARIO ENGINE.

### 3.11 POWER BI / WEB PRESENTATION
- **Purpose:** Communicate insight to a business/stakeholder audience.
- **Inputs:** Analytical and decision outputs.
- **Outputs:** Dashboard (Power BI) and business-first website.
- **Technology:** Power BI Desktop; static web frontend (see Web Application Architecture).
- **Dependencies:** All upstream layers.

---

## 4. Data Provenance & Honesty Rule

Throughout every layer, three categories of data must remain **explicitly separated** and clearly labeled:

| Category | Meaning | Examples |
|---|---|---|
| **A. OBSERVED DATA** | Actual source fields from the dataset | daily units sold, selling price, calendar/events, product/store hierarchy |
| **B. DERIVED DATA** | Calculated from observed data | demand statistics, trend, seasonality, forecasts, forecast accuracy, revenue/contribution |
| **C. SIMULATED DATA / ASSUMPTIONS** | Operational assumptions we set | starting inventory, supplier lead time, service level, safety stock policy, reorder policy, simulated stockouts |

**Rule:** Simulated assumptions and their resulting stockouts are *never* presented as real company data. All artifacts, dashboards, and the website must label simulated values and state the assumptions that produced them.

---

## 5. Planned Technology Stack (justified by business purpose)

| Purpose served | Technology | Why it serves the business/analytical goal |
|---|---|---|
| Source of truth / SQL analytics | **PostgreSQL 17** | Referential integrity + standard SQL for auditable KPI definitions. |
| Data manipulation & analytics | **Python 3.14 + pandas + numpy** | Industry-standard analyst tooling, readable, reproducible. |
| DB connectivity | **psycopg2 / SQLAlchemy** | Needed to move data between Python and PostgreSQL. (Can be installed in a later phase.) |
| Warehouse mgmt | **dbt** *(optional, later)* | Testable, versioned SQL transformations. Chosen only if it adds value beyond plain SQL. |
| Forecasting | **statsmodels** (ETS/ARIMA), **scikit-learn** (ML) | Statistical + ML baselines compared honestly. *(Install in later phase.)* |
| Version control | **Git** | Reproducibility and professional workflow. |
| Dashboard | **Power BI** | Industry-standard BI tool, aligned with the recruiter-facing BI narrative. |
| Website | **Static frontend (HTML/CSS/JS or lightweight framework)** | Business-first communication; no heavy runtime requirement. |
| Testing | **pytest** | Data/feature/decision correctness. |

**Principle:** No technology is added merely for résumé keyword collection. Every item must map to a business or analytical purpose. If a tool costs more in complexity than it returns in correctness/communication, it is dropped.

---

## 6. Dependency Summary for Future Phases

Each future phase depends only on the outputs of prior layers:

1. **Phase 1 (Data & Warehousing):** Source → Validation → ETL → PostgreSQL schema + SQL analytical views.
2. **Phase 2 (Analytics & Forecasting):** Needs curated warehouse + analytical views (Phase 1).
3. **Phase 3 (Inventory, Scenario, Decision):** Needs forecasts (Phase 2).
4. **Phase 4 (Presentation):** Needs decision/analytical outputs (Phase 3).

Nothing in a later phase can start until its upstream dependency is populated and validated.
