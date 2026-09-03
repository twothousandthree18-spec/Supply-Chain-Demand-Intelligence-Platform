# Power BI Architecture

**Phase 0 — Design only. The dashboard has NOT been built.**

## 1. Goal

Translate the analytical and decision outputs into a stakeholder-readable BI solution. Power BI connects to the analytical PostgreSQL views/layers and to decision outputs.

## 2. Planned Pages

| # | Page | Purpose | Major KPIs |
|---|---|---|---|
| 1 | **Executive Control Tower** | Top-level business health at a glance. | Total revenue, total units, revenue growth, category contribution, store/region contribution, headline stockout-risk & excess indicators. |
| 2 | **Demand Intelligence** | Demand patterns and drivers. | Trend, seasonality indexes, volatility (CV), demand growth, top demand entities. |
| 3 | **Product Performance** | Product & category contribution/value. | Revenue/units/price per product, product & category contribution share, growth, Pareto ranking. |
| 4 | **Store & Regional Performance** | Performance across stores/states/regions. | Revenue, units, growth by store/region; benchmarking across hierarchy. |
| 5 | **Forecasting** | Forecasts vs actuals and accuracy. | Forecast vs realized, forecast intervals, WMAE/WRMSE/bias by entity, model selection summary. |
| 6 | **Inventory Risk** | Simulated inventory risk dashboard. | Inventory position, days of inventory, stockout risk, excess inventory, safety stock vs reorder point, service level achieved. *(All labeled SIMULATED / Assumption-based.)* |
| 7 | **Action Center** | Prioritized operational recommendations. | Recommendation list (REORDER / MONITOR / REDUCE / HIGH STOCKOUT RISK / EXCESS / NO ACTION), evidence, impact, entity. |
| 8 | **Scenario Analysis** | Compare scenarios side by side. | KPI deltas vs baseline (service level, stockout, excess, inventory, reorder activity) per scenario. |

## 3. Data Provenance on Every Page

- Observed KPIs (sales, revenue, price, growth) labeled as observed.
- Derived KPIs (forecasts, accuracy, demand statistics) labeled as derived.
- Simulated KPIs (inventory, stockout, excess, service level) labeled **SIMULATED** with the assumption set displayed.
- Consistent Obsidian/Deep-Jade/Electric-Jade/Champagne/Soft-White design tokens (see `docs/design_system.md`).

## 4. Files / Artifacts (future)

- `reports/powerbi/` — `.pbix` project, supporting data-prep queries, and a KPI dictionary.
- Maintainability: KPI definitions originate in the SQL analytical layer, so Power BI references tested views rather than duplicating logic.
