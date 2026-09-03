# Analytical Architecture

**Phase 0 — Design only. No analysis has been performed.**

This document defines the planned analytical areas. Each area maps to a business question and a set of KPIs. Every KPI will have one tested definition in the SQL analytical layer.

---

## A. SALES / COMMERCIAL

**Purpose:** Understand revenue and volume performance and where business value is concentrated.

| KPI | Definition intent |
|---|---|
| Revenue | sum(units_sold × sell_price) over a period (note: price is weekly; units daily — documented derivation). |
| Units | sum(units_sold). |
| Price | avg / weighted sell_price. Price elasticity vs units (analytical, not causal claim). |
| Growth | period-over-period % change in revenue/units (YoY, QoQ, WoW). |
| Product contribution | share of revenue/units per product (Pareto / top-N). |
| Category contribution | share of revenue/units per department/category. |

**Responsibility:** SQL views + tested aggregations. Basis for "Product Performance" and "Executive Control Tower."

## B. DEMAND

**Purpose:** Characterize demand patterns to inform forecasting and inventory logic.

| Metric | Intent |
|---|---|
| Trend | direction and slope of demand over time. |
| Seasonality | weekly/monthly/annual repeating patterns via seasonal indices. |
| Volatility | coefficient of variation (std/mean) of daily units. |
| Demand growth | rate of change of mean demand. |
| Product/store demand patterns | segmentation of entities by volume×volatility (e.g., high-volume/low-variance vs low-volume/high-variance). |

**Responsibility:** PYTHON ANALYTICS; feeds forecasting feature design and risk classification.

## C. FORECASTING

| Component | Intent |
|---|---|
| Baseline models | naive / seasonal-naive / moving average as lower-bound comparators. |
| Statistical models | exponential smoothing (ETS), classical decomposition, ARIMA-family where justified. |
| ML forecasting | gradient-boosted / regression-based forecasting ONLY where computationally justified and when it beats baselines on holdout — never assumed superior. |
| Time-based validation | rolling/origin-based holdout; chronological only. |
| Forecast accuracy | MAE, RMSE, WMAE, WRMSE, bias, per entity and aggregate. |

**Responsibility:** FORECASTING ENGINE. All details in `docs/forecasting_architecture.md`.

## D. INVENTORY

| Metric | Intent |
|---|---|
| Inventory position | on-hand + on-order − backorder, over time. |
| Safety stock | buffer = f(demand variability, lead time, service level). |
| Reorder point | expected demand over lead time + safety stock. |
| Days of inventory | on-hand ÷ average daily demand. |
| Stockout risk | probability of projected stockout given forecast + variability. |
| Excess inventory | units (or value) above a target coverage ceiling. |

**Responsibility:** INVENTORY SIMULATION. All values are SIMULATED and must be labeled as such. Details in `docs/inventory_simulation_architecture.md`.

## E. DECISION SUPPORT

| Component | Intent |
|---|---|
| Reorder recommendation | when/quantity to reorder vs reorder point + policy. |
| Risk classification | place products/stores into risk tiers (stockout / excess / healthy). |
| Scenario analysis | re-run under alternative business conditions; compare KPIs. |
| Business action | translate evidence into an explicit recommended action. |

**Responsibility:** SCENARIO ENGINE + DECISION ENGINE. Details in `docs/scenario_engine.md` and `docs/decision_engine.md`.

---

## KPI Definition Policy

- One canonical definition per KPI, implemented once in the SQL analytical layer.
- All KPI definitions recorded in `docs/kpi_definitions.md` (added in a later phase).
- Aggregations are validated by SQL tests to guarantee correctness across grain changes (daily→weekly→monthly, store/product rollups).
