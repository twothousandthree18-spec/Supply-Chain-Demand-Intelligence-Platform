# Phase 6 — Web / Product Presentation Layer: Architecture Specification (Steps 1–2)

**Phase 6 goal:** A professional, business-first web interface that presents the completed analytics
system as a decision-intelligence product. This document is the **build contract for Steps 1–2**
(architecture + route/component/data contracts + locked theme + application shell/navigation + global
styling foundation). Analytical pages (Steps 3–7) are implemented later **on top of this contract** and
are not part of this step.

All Phases 1–5 outputs are **LOCKED production artifacts**. This layer only *reads* already-materialized
aggregated/derived surfaces; it never rebuilds forecasting/inventory/scenario logic and never queries the
59M-row `fact_daily_sales` directly.

---

## 1. Decisions & Rationale

| Decision | Choice | Rationale |
|---|---|---|
| Framework | **FastAPI (Python) + static HTML/CSS/JS frontend** | Project is Python/PostgreSQL-end-to-end (`src/api`, `src/web` reserved dirs). FastAPI provides typed (pydantic) contracts, server-side filtering/pagination, and a small dependency footprint. Serving static assets via FastAPI StaticFiles keeps one process. |
| Frontend rendering | Static HTML + JS that fetches JSON from `/api/**` | Reads the completed data layer (the brief's server-side filtering/pagination). No heavy SPA framework; reusable vanilla JS components keep it lightweight and testable. |
| Data access | `src/web/services/` (SQL over psycopg2 via `src/etl/db_utils.connect`) returning `src/web/contracts/` pydantic models | Data-access code is strictly separated from presentation; contracts are typed and versionable. |
| Rendering testability | Python `httpx` + FastAPI TestClient exercising real `/api` reads (read-only) | Validates page-render proxying, navigation, contract shapes, empty/undefined states, pagination. |
| Provenance | Every derived/simulated response carries `data_provenance` on each row; UI renders a chip | Locked Phase-5 provenance contract (derived vs simulated; never present simulated as observed). |

**Not chosen / reasons:** no Vue/React/Next (adds build tooling and a runtime contrary to the lightweight
architecture doc); no Django (heavier than needed); no live ETL from the web layer (severely against the
locked-data and no-`fact_daily_sales` rules).

---

## 2. Route / Page Map

The SPA shell serves one document; client-side JS toggles **views** bound to `/api` resources.

### Views (product areas)
| # | View key | Route | Title | Primary `/api` resource(s) |
|---|---|---|---|---|
| 1 | `executive` | `/` (or `/#/executive`) | Executive Dashboard | `kpis/executive`, `executive/signals`, `kpis/headline` |
| 2 | `demand` | `/#/demand` | Demand Intelligence | `analytics/demand`, `analytics/demand/seasonality`, `analytics/demand/dow`, `analytics/demand/segments` |
| 3 | `forecast` | `/#/forecast` | Forecast Intelligence | `forecast/accuracy`, `forecast/models`, `forecast/series` |
| 4 | `inventory` | `/#/inventory` | Inventory Intelligence | `inventory/summary`, `inventory/horizon`, `inventory/risk` |
| 5 | `scenario` | `/#/scenario` | Scenario Intelligence | `scenario/runs`, `scenario/deltas`, `scenario/comparison` |
| 6 | `risk` | `/#/risk` | Operational Risk / Priority | `risk/rankings?risk_type=stockout\u007cexcess`, `risk/drivers` |

### App shell (Steps 1–2 scope)
- `GET /` → serves `src/web/static/index.html` (shell + nav + theme foundation).
- `GET /static/*` → FastAPI `StaticFiles` (CSS/JS).
- `GET /api/health` → liveness + DB reachability + locked-cursor summary.
- `GET /api/meta` → provenance/limitation/empty-state metadata document (drives shell notes).
- Each view's data endpoints (full list below) are defined as **contracts now**, implemented by the data
  layer service in Steps 3–7.

---

## 3. Component Map

```
src/web/
  main.py                 # ASGI app factory (FastAPI), static mount, router wiring
  settings.py             # pydantic-settings config (DB via env, static dirs)
  contracts/
    __init__.py
    common.py             # Provenance enum, Paginated envelope, MetricValue (value+provenance+undefined)
    dashboard.py          # executive/demand/forecast/inventory/scenario/risk payload models
  services/
    __init__.py
    db.py                 # get_db cursor dependency (reuses src.etl.db_utils.connect)
    executive.py          # headline KPIs + operational signals (v_* + fact_scenario_result rank runs)
    demand.py             # fact_demand_analysis / seasonality / dow / segments aggregations
    forecast.py           # fact_forecast_evaluation / model_registry / fact_forecast (bounded)
    inventory.py          # fact_inventory_simulation (28-day bounded) + baseline policy snapshot
    scenario.py           # fact_scenario_result groups + deltas vs baseline + comparison empty-state
    risk.py               # stockout/excess rankings (rank runs 6/7) + risk_components drivers
  routers/
    __init__.py
    meta.py               # health + meta
    dashboard.py          # /kpis/** , /analytics/**, /forecast/**, /inventory/**, /scenario/**, /risk/**
  static/                 # frontend (locked theme)
    index.html
    css/tokens.css        # 5-color design tokens (single source)
    css/base.css          # reset + typography + layout + nav + cards + chips + tables + states
    js/app.js             # SPA shell: nav, router, fetch wrapper, provenance chip renderer
    js/components/        # reusable client components (kpi-card, data-table, metric-value) - later steps
```

**Reusability:** each service returns pydantic models so any frontend component consumes typed JSON; the
`MetricValue` wrapper encodes `value | null` + `provenance`, so the UI can always render "—" for undefined
and label provenance.

---

## 4. Data-Access Contracts

All endpoints are **query-only** (SELECT); none modify state. Cross-cutting guarantees:
- **Period/day** filters are bounded (week-level views read `v_*`; day views read the 28-day forecast/
  inventory horizon 1942..1969 only). No endpoint accepts a filter that scans `fact_daily_sales`.
- **Pagination** via a shared `Page(page, page_size, total, items)` envelope; server-side LIMIT/OFFSET +
  `count(*)` over the filtered predicate. Default page_size 25, max 200.
- **Provenance** on every row: `data_provenance` ∈ {observed, derived, simulated}.

### 4.1 Executive
| Endpoint | Source | Grain | Returns |
|---|---|---|---|
| `GET /api/kpis/headline` | `v_revenue`, `v_units`, `v_growth_wow/qoq/yoy` | week/quarter/year | revenue, units, weighted price, WoW/QoQ/YoY %, last-N weeks trend |
| `GET /api/kpis/executive` | `v_product_contribution`, `v_department_contribution`, `v_category_contribution`, `v_store_contribution`, `v_state_contribution` | entity | Pareto + share %, ranked |
| `GET /api/executive/signals` | `fact_scenario_result` (rank runs) + `fact_inventory_simulation` (baseline) | rank | high-risk series count, service level, days-of-inventory, top signals |

### 4.2 Demand
| Endpoint | Source | Returns |
|---|---|---|
| `GET /api/analytics/demand` | `fact_demand_analysis` | trend direction, growth, CV, volatility class, pattern, risk-cell counts (server-side filtered) |
| `GET /api/analytics/demand/segments` | `fact_demand_analysis` | volume×volatility matrix counts + risk_category |
| `GET /api/analytics/demand/seasonality` | `fact_demand_seasonality` | strength, peak/trough month, seasonal index by month |
| `GET /api/analytics/demand/dow` | `fact_demand_seasonality_dow` | DOW indices by `scope_type` |

### 4.3 Forecast
| Endpoint | Source | Returns |
|---|---|---|
| `GET /api/forecast/accuracy` | `fact_forecast_evaluation` + `fact_demand_analysis` | MAE/RMSE/WMAE/WRMSE/bias per model + support count (locked 64-series caveat) |
| `GET /api/forecast/models` | `model_registry` | model list, `is_selected`, family, metrics_json, selection rationale |
| `GET /api/forecast/series?series=...` | `fact_forecast` (is_final, bounded 28-day) | forecast_value/lower/upper per date for one series (1:1 no fan-out) |

### 4.4 Inventory
| Endpoint | Source | Returns |
|---|---|---|
| `GET /api/inventory/summary` | `fact_inventory_simulation` (28-day) + `fact_scenario_result` baseline | on-hand, on-order, backorder, days-of-inventory, service level, position aggregates (sim) |
| `GET /api/inventory/horizon?series=...` | `fact_inventory_simulation` (bounded) | per-day position/on-hand/on-order/stockout for one series |
| `GET /api/inventory/policy` | `fact_scenario_result` baseline + `assumption_set` | safety stock, reorder point, reorder qty, lead time, target service |

### 4.5 Scenario
| Endpoint | Source | Returns |
|---|---|---|
| `GET /api/scenario/runs` | `fact_scenario_run` × `scenario` | run id → name/type/assumption, status, records_processed |
| `GET /api/scenario/deltas` | `fact_scenario_result` | per scenario vs baseline: delta stockout/service/excess/fill/position (sim) |
| `GET /api/scenario/comparison` | `fact_scenario_comparison` | **empty-state**: 0 rows → `{present: false, reason: "no action_tradeoff scenario"}` (never fabricated) |

### 4.6 Risk
| Endpoint | Source | Returns |
|---|---|---|
| `GET /api/risk/rankings?risk_type={stockout,excess}&tier=&dept=&store=&page=` | `fact_scenario_result` (rank runs 6/7) | ranked series (risk_rank 1..30,490 unique), score, tier, drivers, paginated |
| `GET /api/risk/drivers?series=...` | `fact_scenario_result` | risk_components breakdown for a series |

---

## 5. Locked Theme (tokens)

Single source-of-truth in `src/web/static/css/tokens.css` — MUST equal the Phase 6 brief and the existing
`docs/design_system.md` palette. No off-palette color is introduced.

| Token | Value | Semantic use |
|---|---|---|
| `--color-obsidian` | `#090B0A` | primary dark surface/background |
| `--color-deep-jade` | `#123C35` | secondary surface / panels / bands |
| `--color-electric-jade` | `#19E6B1` | positive / active / highlight / accent |
| `--color-champagne` | `#D8C39B` | secondary emphasis / warning / attention |
| `--color-soft-white` | `#EDEFEA` | primary readable text / light background |

Derived semantic states (documented; derived conservatively from the tokens, per design-system §1):
- `--color-success` = electric-jade, `--color-warning` = champagne, `--color-danger` = a **derived** darker
  red-orange **only** defined as a documented alias (from the palette family so nothing invents a palette);
  it is used solely for danger states and documented.
- Typography: geometric display font + readable data sans-serif; numeric class for KPI/table digits.
- Spacing: 4px base grid; consistent card padding; 10–11pt data text minimum.

---

## 6. Global Styling Foundation (scope of this step)

`tokens.css` (palette + spacing + type + radius + shadow) and `base.css` (reset, layout grid, navigation,
cards/panels, KPI grid, chips for provenance/risk-tier, tables, pagination controls, and loading/empty/
error state classes) — used by every later view.
- **Accessibility:** contrast-safe text on obsidian/soft-white; focus-visible states; `prefers-reduced-motion`
  respected; semantic HTML for nav/sections.
- **Responsive:** desktop-first; single-column reflow + horizontal-scroll tables on narrow screens.

---

## 7. Engineering rules enforced in this step

1. **Data-access separation:** only `src/web/services/*` issues SQL; routers/static code never import
   psycopg2. Services return pydantic contracts.
2. **No `fact_daily_sales`** anywhere in `src/web/` (grep-guarded by tests).
3. **No reprocessing:** services only SELECT materialized surfaces; no forecast/inventory/scenario math
   in the web layer.
4. **Typed contracts** (pydantic) for every outbound payload.
5. **Provenance + undefined** carried on every metric; UI renders "—" and provenance chips.
6. **Empty/limitation honesty:** `fact_scenario_comparison` empty-state; ETS/SARIMA 64-series caveat surfaced.
7. **Server-side pagination** for large result sets (risk rankings, demand/matrix counts).
8. Reuse `src/etl/db_utils.connect`; connection lifecycle via a FastAPI dependency.

---

## 8. Acceptance for Steps 1–2

- `GET /api/health` returns DB reachable + locked cursor (units/forecast/inventory/scenario counts).
- `GET /api/meta` returns provenance contract, limitations (pilot, comparison empty), reconciliation anchors.
- Shell renders at `/`; nav lists all 6 product areas; CSS tokens load with the exact 5-color palette.
- Tests cover: shell render, navigation links, theme token values, health/meta contract, and enforcement of
  the no-`fact_daily_sales` + no-reprocessing rules via source scan.

---

## 9. Step 3 — Core API / Data-Integration (delivered)

All endpoints in the §4 data-access table are now implemented and verified by `tests/web/test_api.py`
(**36 passed**). The Step 3 service layer (`services/demand.py`, `forecast.py`, `inventory.py`,
`scenario.py`, `risk.py`) reads only bounded materialized surfaces — `fact_demand_analysis` (30,490),
`fact_demand_seasonality(_dow)`, `model_registry` (6), `fact_forecast_evaluation`, per-series
`fact_forecast` (28-day is_final), the simulated `fact_inventory_simulation` (28-day) + baseline
`fact_scenario_result` + `assumption_set`, `fact_scenario_run`/`fact_scenario_result`, and the
`fact_scenario_result` rank runs (6/7) for risk — plus lookup dims (`dim_product`, `dim_store`,
`dim_department`, `dim_date`). No endpoint scans `fact_daily_sales` and none recomputes
forecast/inventory/scenario math. Server-side filtering, sorting, and pagination (shared `Page`
envelope, page_size cap 200) are enforced on every list endpoint. Measured timings after Step 3 are
all ≤ ~0.7s (inventory summary 0.66s, scenario deltas 0.51s, forecast accuracy 0.46s), so no new
unbounded first-load aggregation was introduced.

---

## 10. Step 4 — Executive Dashboard (delivered)

Built the Executive Dashboard view on top of the Step 3 API, verified by `tests/web/test_executive.py`
(**22 passed**); the full web suite is **74 passed** (`tests/web/`). Components delivered:

**View layout (`#view-executive`)** — a business-filter bar plus four sections, all rendering the
locked palette only (danger family reserved for risk severity):

1. **KPI header (`#exec-kpis`)** — 10 compact cards composed from `/api/kpis/executive` (Revenue,
   Units, Revenue/Units WoW, Revenue QoQ, Revenue YoY), `/api/inventory/summary` (Avg Days of
   Inventory, Avg Service Level), and `/api/executive/signals` (Series at Stockout Risk, Series at
   Excess Risk). Growth values carry direction arrows (▲/▼/→); undefined metrics render literal "—".
2. **Demand performance (`#exec-demand`)** — 12-week revenue & units trend bars, growth-direction
   chips, and a revenue-concentration view (`/api/kpis/contributions`: top products, department
   share, state share) with share bars and ranks. This is the only section scoped by the filters.
3. **Inventory health (`#exec-inventory`)** — simulated service-level and days-of-inventory meters,
   stockout/excess exposure cards, and a concise health read.
4. **Operational signals (`#exec-signals`)** — the ranked signal list (risk type, tier, rank, entity,
   supporting metric = risk score, business explanation) plus a "how to read" legend.

**Filters (`#exec-filter-bar`)** — server-driven via a new bounded `GET /api/meta/dimensions`
endpoint (reads only `dim_department`/`dim_category`/`dim_store` lookup dims). Controls: Department,
Category, State/Region, Store, Product (optional free text), Top contributors (Top-N 5/10/25/50), and
Reset. The `contributions` endpoint already accepts `department|category|product|store|state|region`
(allowlisted `_FILTER_COLUMNS`) and clamps `top_n` to 1..50 (`422` outside). Selecting a filter
re-queries contributions (headline KPIs are cached full-portfolio) and shows a loading state during the
refresh. Non-existent dimension values return 0 rows (never a 5xx).

**Performance** — `Promise.all` fetches the four aggregates in parallel; the stable full-portfolio
calls (kpis/inventory/signals) are cached so only contributions reload on filter change. Documented
first-load ~16s limitation is preserved (headline ~3.1s + contributions ~11.4s + signals ~0.1s).

**Conventions enforced** — provenance chips (observed/derived/simulated), literal "—" for undefined,
compact KPI cards, desktop-first responsive grid, loading/empty/error states, tooltips for metric
explanations, no decorative graphics. Source-level tests confirm `src/web` still never queries
`fact_daily_sales` or the `v_units` view, and that `dimensions()` never scans fact tables.

---

## 11. Step 5 �?" Demand / Forecast / Inventory Intelligence pages (delivered)

Built the three product-area pages on the existing Step 3 APIs, verified by `tests/web/test_pages.py`
(**26 passed**); the full web suite is **100 passed** (`tests/web/`). Three new hash views
(`#/demand`, `#/forecast`, `#/inventory`) routed in `app.js` via `route()` dispatch. Components
delivered:

**Demand Intelligence (`#view-demand`)** �?" server-side filter bar + four sections scoped by filters:
1. **Summary (`#demand-summary`)** �?" series count and filtered-row count with derived provenance.
2. **Production matrix (`#demand-matrix`)** �?" segment_volume x segment_volatility heat grid from
   `/api/analytics/demand/segments` (High/Medium/Low both axes), cell counts with darker fill.
3. **Risk breakdown (`#demand-risk`)** �?" Critical / High / Moderate count chips.
4. **Series table (`#demand-table`)** �?" paginated, sortable rows of product/store*cv, mean daily
   units, trend, volume/volatility/risk, demand class; server-side pagination (page 1..N) and sort
   tokens (cv_desc, mean_daily_units, risk).

**Filters (`d-department/category/state/store/trend/volatility/volume/risk/product/page-size/Reset`)**
�?" the demand service `_filter_clause` allowlist was extended with `department`/`category`
(correlated `EXISTS` on `dim_department`/`dim_category`), `state` (`dim_store.state_id`) and `region`
(`dim_store.region_id`); product now matches `p.product_id` and store matches `st.store_id`. The
`/api/analytics/demand` and `/api/analytics/demand/segments` routers pass these through. Verified live:
`department=FOODS_2` bounds the series table from 30,490 to 3,980. Reset clears all filters and page.

**Forecast Intelligence (`#view-forecast`)** �?" model selection + per-series drill-down:
1. **Model selection (`#forecast-selection`)** �?" champion card from `/api/forecast/models` (selected
   family = baseline/naive) with MAE/RMSE/WMAE/WRMSE/Bias and selection rationale.
2. **Accuracy table (`#forecast-accuracy`)** �?" all six models with a support column and a pilot
   badge/caveat. Models 1�?"4 show support 30,490; models 5�?"6 (ets_holt_winters, sarima) show a
   **pilot** badge and support **64**, with an explicit caveat that they were evaluated only on the
   64-series pilot and are not comparable to the all-series baselines without re-scoring.
3. **Series card (`#forecast-series-card`)** �?" a single series' bounded 28-day final forecast (`origin`
   1,941, horizons 1�?"28) loaded only on "View series forecast". Bounded to that one series (no
   fan-out), forecast/ lower/ upper bars + table.

**Inventory Intelligence (`#view-inventory`)** �?" simulated provenance throughout:
1. **Summary (`#inventory-summary`)** �?" On-hand, On-order, Backorder, Inventory position, Days of
   inventory, Service level (75.1% vs ~95% target), Fill rate, Safety stock, Reorder point, Stockout
   and Excess exposure. Tagged **simulated** with header text "Not observed inventory."
2. **Policy (`#inventory-policy`)** �?" `/api/inventory/policy` assumptions: baseline set,
   safety-stock formula (z x sigma x lead-time demand), reorder policy (s,Q), capped coverage, lead
   time 7 days, target service.
3. **Horizon (`#inventory-horizon`)** �?" a single series' bounded 28-row simulated horizon (position/
   on-hand/on-order/stockout) loaded only on "View series horizon"; red danger bars mark stockout skyline
   days.

**Conventions enforced** �?" provenance chips (derived/simulated), literal "�?"" for undefined metrics,
compact cards, desktop-first responsive grid, loading/empty/error states, tooltips. Forecast caveats for
the 64-series pilot and inventory "simulated" disclaimers are surfaced directly on-page. Source-level
tests (`test_pages.py`) re-confirm `src/web` never queries `fact_daily_sales` or `v_units`, that demand
dimension filters use bounded `EXISTS` subqueries on the small dimension tables, and that the locked
5-color palette (plus the documented danger family `#C25A3A`/`#8F3D2B`) is the only fill set in Step-5
CSS.

---

## 12. Step 6 �?" Scenario Intelligence & Operational Risk pages (delivered)

Built the Scenario and Risk views on the existing scenario/risk APIs, verified by `tests/web/test_step6.py`
(**29 passed**); the full web suite is **129 passed** (`tests/web/`). Two new hash views (`#/scenario`,
`#/risk`) routed in `app.js` via `route()` dispatch (added `loadScenario()`/`loadRisk()`).

**Scenario Intelligence (`#view-scenario`)** �?" filter bar + three sections, all simulated:
1. **Run status (`#scenario-status`)** �?" the 7 scenario runs from `/api/scenario/runs`: the `baseline`,
   four simulation scenarios (demand shock, lead-time change, service-level change, reorder policy) and
   two ranking scenarios. Each row shows scenario type, a simulation/ranking/baseline label, assumption
   set, status/records-processed, and run date. All tagged `simulated`.
2. **Deltas vs baseline (`#scenario-deltas`)** �?" `/api/scenario/deltas` (6 rows; baseline excluded).
   Columns: stockout days, service level, fill rate, reorder frequency, avg inventory position, excess
   days, avg days of inventory, series count. Service-level/fill-rate deltas are rendered as percentage
   points (x100). Ranking scenarios carry no delta aggregates and show literal "�?"" with a "ranking · no
   delta" badge; simulation scenarios show their deltas. Upside/downside tinted within the palette.
3. **Action tradeoff comparison (`#scenario-comparison`)** �?" `/api/scenario/comparison` is a locked
   empty state (0 rows by design). Rendered prominently as "No action-tradeoff comparison is currently
   available." and explicitly notes no recommendations are shown because
   `fact_replenishment_recommendation` is not yet populated; nothing is fabricated.

**Filters (`sc-type` simulation/ranking, `sc-name`, Reset)** �?" client-side re-render of the already
fetched scenario lists, keeping the comparison a stable empty state.

**Operational Risk / Priority (`#view-risk`)** �?" filter bar + three sections, all simulated:
1. **Risk distribution (`#risk-distribution`)** �?" ranked-series count matching the filters, ranking
   basis, tier levels, and drill-down hint (server-side count, no page-level fabrication).
2. **Risk worklist (`#risk-table`)** �?" `/api/risk/rankings` (stockout or excess) with native risk rank
   (deterministic 1..30,490), tier chip, product · store, department, category, state/region, risk score
   (0�?"1 shown as a readable %), and dominant driver. Rows are clickable for drill-down.
3. **Risk driver (`#risk-driver`)** �?" `/api/risk/drivers?series=` evidence panel: rank/score/tier plus
   the risk-component breakdown (urgency, service gap, volume rank, stockout probability, volatility
   rank). Clicking a ranked series opens it; unknown series show an explicit empty state.

**Filters (`rk-type` stockout/excess, `rk-tier`, `rk-department`, `rk-category`, `rk-state`,
`rk-store`, `rk-product`, `rk-topn` 25/50/100/200, Reset)** �?" all server-side through the existing
`/api/risk/rankings` endpoint, which was extended to accept and thread the dimension filters. The risk
service `_filter_clause` allowed-list was widened with `department`/`category` (correlated `EXISTS` on
`dim_department`/`dim_category`) and `state`/`region` (`dim_store`), mirroring the demand pattern; the
rankings SELECT and `RiskRank` contract were extended to return `department`, `category`, `state`,
`region` display fields so each row shows the entity's dimension path without extra client lookups.
Ranking stays deterministic by native `risk_rank`.

**Performance** �?" scenario page loads runs + deltas + comparison in one `Promise.all`; risk page loads
the paginated worklist plus a lightweight `page_size=1` count for the distribution. No `fact_scenario_result`
bulk load (never the 213,430 rows), no `fact_daily_sales`, no duplicating scenario math in the browser.

**Conventions enforced** �?" simulated provenance chips on every section; literal "�?"" for undefined
(including ranking-run nulls); desktop-first responsive grid; loading/empty/error states; tooltips.
Source-level tests confirm `src/web` never queries `fact_daily_sales`/`v_units`, risk uses correlated
dim-subqueries only, and Step-6 CSS adds no off-palette hue beyond the locked palette + danger family.
## 13. Step 7 �?" Shared UX integration, filters, drill-downs, responsiveness, accessibility (delivered)

Step 7 closed out the product layer with a consistent, accessible, responsive interaction model across
all six pages, verified by `tests/web/test_step7.py` (**49 passed**) and a Playwright pass over every page at
both desktop (1440px) and mobile (375/360px). The full web suite is **178 passed** (`tests/web/`).

**Shared data-table UX.** Every JS-rendered table now emits `scope="col"` on its `<th>` (demand, model
accuracy, forecast detail, inventory horizon, scenario deltas/runs, risk worklist) so screen readers
associate header with cell. Tables render inside `.table-wrap { overflow-x: auto }`, so a wide table
scrolls in-place rather than inflating the page; row counts and pagination totals (`pagination__total`)
are labelled for assistive tech, and disabled pagination buttons carry `disabled`.

**Lead/filter system & cross-page nav.** Each page shares the labelled filter group (`role="group"` +
`aria-label`), server-side pagination/filters only (no bulk loads), encoded query-safe values, and a Reset
that truthfully clears the real control IDs (`filter-reset`, `d-reset`, `sc-reset`, `rk-reset`). A breadcrumb
(`<nav class="crumb"><ol>`, `aria-current="page"`) links back to `#/executive` from every view; the app
nav exposes six labelled routes.

**Drill-down model.** Risk ranked rows open the risk-driver evidence panel on click and on keyboard
(`keydown` + `Enter`/Space, `tabindex="0"`, `aria-busy`, focus retained); series drill-downs (forecast
detail, inventory horizon) stay bounded (&#8804; 28 points / 28 days) and likewise use `scope="col"`.
Drill-down panels provide an explicit back affordance.

**Responsiveness.** Breakpoints at 1024 / 760 / 480px. Nav becomes a tappable horizontal scroller at
&#8804; 760px; filters stack full-width; the KPI/grid tracks use `minmax(min(100%, 130px), 1fr)` and clip
horizontally (`overflow-x: clip`) at every width so item min-content cannot force page overflow; growth
chips wrap; wide tables keep scrolling in their own wrap. Verified: every page reports
`scrollWidth == clientWidth` (no horizontal page overflow) at desktop and mobile.

**Accessibility & correctness.** Keyboard drill-down verified live (Enter opens the risk driver), focus
visible, reduced-motion respected, colour bound strictly to the locked 5-colour palette plus the documented
danger severity family.

**Genuine defects fixed during Step 7 validation.** (1) `.exec-grid` and the KPI grid forced ~498px+
track widths at mobile; converted to `minmax(0, 1fr)` / `minmax(min(100%, 130px), 1fr)`. (2) growth
chips with `white-space: nowrap` forced ~464px pills; now wrap. (3) long KPI sub-captions ("Simulated ·
avg over the 28-day horizon") hit a grid/flex min-content bug that pushed `scrollWidth` to 240px and page
to 445px at mobile and 1483px at desktop; fixed with `min-width: 0` + `overflow-wrap: anywhere` on
`.kpi__sub`/`.metric` children and `overflow-x: clip` on the KPI/grid containers (page now 360/360 at
mobile, 1440/1440 at desktop). (4) `.app-header` scrollWidth inflated by nav links; clipped. (5) risk
matrix `1fr` tracks overflowed at small widths; cells now `min-width: 0` and the matrix clips.

**Performance safeguards retained.** No `fact_scenario_result` bulk load (never the 213,430 rows),
no `fact_daily_sales`/`v_units` from `src/web`, server-side pagination and dimension filters only, risk
distribution via a lightweight `page_size=1` probe, scenario comparison stays an explicit empty state,
executive reuse of fetched series data.

_This is the final step of Phase 6 scope; no deploy and no further analytical features beyond Phases 1-6.
