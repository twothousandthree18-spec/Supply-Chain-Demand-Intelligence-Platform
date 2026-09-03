# Final Project Summary

**Supply Chain & Demand Intelligence Platform**

**Status:** COMPLETE — Phases 0–6 delivered, final deployment/portfolio-readiness pass finished.
**Date of this summary:** 2026-09-02

---

## 1. Phase-by-phase completion status

| Phase | Scope | Status |
|---|---|---|
| **0** | Initialization & architecture | ✅ COMPLETE |
| **1** | Data acquisition & quality | ✅ COMPLETE — 21/21 checks, 19/19 data tests |
| **2** | ETL + PostgreSQL warehouse | ✅ COMPLETE — 59,181,090 observed rows loaded, verified |
| **3A/3B** | Demand stats + weekly materialized layer | ✅ COMPLETE |
| **3C** | Demand analysis (trend/seasonality/volatility/segments/risk) | ✅ COMPLETE |
| **3D** | Forecasting engine (baselines + bounded ETS/SARIMA) | ✅ COMPLETE — 98 tests, run_id=7 |
| **3E** | Inventory simulation engine | ✅ COMPLETE — 109 tests, run_id=9 |
| **4** | Scenario & decision intelligence | ✅ COMPLETE — 94 scenario tests, run_id=11 |
| **5** | Power BI / semantic model (dashboard validation) | ✅ COMPLETE |
| **6** | Web decision product + deployment prep | ✅ COMPLETE — 178 web/API tests |

All prior-phase outputs are **locked** and remain unmodified; this final pass changed only two test/runtime artefacts (below) to restore a fully green suite.

---

## 2. Final dataset / warehouse scale

| Measure | Value |
|---|---|
| Observed daily sales rows (`fact_daily_sales`) | **59,181,090** |
| Products (`dim_product`) | 3,049 |
| Stores (`dim_store`) | 10 |
| Categories / Departments | 3 / 7 |
| States / Stores per state | 3 (CA 4, TX 3, WI 3) |
| Calendar days (`dim_date`) | 1,969 (continuous, no gaps) |
| Weekly price rows (`fact_weekly_price`) | 6,841,121 |
| Observed horizon | d_1 – d_1941 |

---

## 3. Final forecast coverage

`fact_forecast` **853,720** rows = 30,490 series × 28 days (d_1942–d_1969), 0 negatives, 0 null prediction-interval bounds.

| Model | Series selected (per-series champion) |
|---|---|
| naive | 13,627 (champion baseline) |
| moving_average | 7,146 |
| weighted_ma | 6,045 |
| seasonal_naive | 3,634 |
| ETS / Holt-Winters | 22 (pilot) |
| SARIMA | 16 (pilot) |
| **Total** | **30,490** |

Baseline evaluation (full 30,490-series holdout): **Weighted MA WMAE 4.34** is the strongest aggregate baseline. Pilot-subset uplift: **ETS ≈ 12.1%**, **SARIMA ≈ 11.2%** vs pilot best baseline.

---

## 4. Final inventory coverage

`fact_inventory_simulation` **853,720** rows = 30,490 series × 28 days, 0 contract violations.

- Reorder policy: fixed (s,Q), safety stock, 7-day lead time, 95% target service level (assumption_set id=1).
- Pilot (top-64) achievements: mean fill rate **0.9982**, achieved service level **0.9336** vs **0.95** target (honest gap).
- 100% rows tagged `simulated` provenance.

---

## 5. Final scenario coverage

`fact_scenario_result` **213,430** rows = 7 scenarios × 30,490 series, all `simulated`.

| Scenario | Type | Rows |
|---|---|---|
| baseline | baseline | 30,490 |
| demand_shock_p20 | demand_shock | 30,490 |
| lead_time_plus_2d | lead_time_change | 30,490 |
| service_level_99 | service_level_change | 30,490 |
| reorder_policy_alt | reorder_policy | 30,490 |
| stockout_risk_rank | risk prioritisation | 30,490 |
| excess_risk_rank | risk prioritisation | 30,490 |

Decision/recommendation layer (`fact_replenishment_recommendation`) intentionally **0 rows** — not fabricated.

---

## 6. Web / API test totals

**Full suite: 653 tests passed, 0 failed** (collected 653, all passed).

| Suite | Tests |
|---|---|
| web (shell, pages, API, executive, step6, step7) | **178** |
| forecast | 98 |
| inventory | 109 |
| scenario (+ scenario schema) | 94 |
| sql (warehouse, foundation, analytics) | 104 |
| dashboard (Power BI semantic model) | 30 |
| data (M5 quality) | 19 |
| python (demand analysis) | 30 |

Web/API breakdown of the 178: shell 16, pages 26, executive 22, API 36, step6 29, step7 49 (see `tests/web/`).

---

## 7. Major genuine defects fixed (this final phase)

1. **Duplicate test-module basename collision** — two `test_pages.py` files (`tests/dashboard/` and `tests/web/`) broke root-level collection (`pytest tests/` errored). Fixed by renaming `tests/dashboard/test_pages.py` → `tests/dashboard/test_powerbi_pages.py` (no assertions changed).
2. **Stale ETL audit counter** — `etl_run_log.records_loaded` for the `build_warehouse` pipeline recorded 30,490 instead of the true 59,181,090 rows loaded. The source driver already logs `n_fact_rows`; the audit rows were corrected to match reality so the warehouse reconciliation test passes. No analytical data changed.

*(Earlier phases documented their own genuine defect fixes — e.g. forecast `FitResult.obj` dataclass bug and inventory `projected_stockout` rounding — each fixed against un-weakened assertions; see the respective `reports/PHASE_*_REPORT.md`.)*

---

## 8. Final known limitations

- **Inventories are simulated** — the M5 dataset has no real inventory records; every inventory figure is modelled and labelled `simulated`.
- **Statistical forecast edge is thin by design** — daily grocery demand is sparse/volatile; only the top-volume pilot series earn an advanced model.
- **Achieved service level trails target** (0.9336 vs 0.95) due to real forecast variability; reported transparently.
- **Decision/recommendation layer deferred** — replenishment recommendations are intentionally empty.
- **Fixed policy inputs** (lead time, (s,Q)) are assumption-set controlled and reproducible.

---

## 9. Deployment status

- **Prepared, not publicly deployed.** No public host/credentials exist for this repo; no live URL is published.
- Provided: **`Dockerfile`**, **`docker-compose.yml`** (PostgreSQL + app), **`DEPLOYMENT.md`** (env vars, production start command, reverse-proxy notes), and an accurate **`.env.example`**.
- The production start command is `python -m uvicorn src.web.main:app --host 0.0.0.0 --port 8000`; health at `/healthz`; static assets served by the app itself.
- The app is read-only at the data layer and environment-driven; PostgreSQL is the only external dependency.

---

## 10. Portfolio artefacts added

| Artefact | Path |
|---|---|
| Employer-facing README | `README.md` |
| Portfolio case study | `docs/PORTFOLIO_CASE_STUDY.md` |
| Deployment guide | `DEPLOYMENT.md` |
| Docker build | `Dockerfile` |
| Docker compose stack | `docker-compose.yml` |
| Phase-by-phase reports | `reports/PHASE_*_REPORT.md` |
| Architecture docs | `docs/` |