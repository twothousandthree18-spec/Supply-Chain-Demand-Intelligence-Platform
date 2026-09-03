# Web Application Architecture

**Phase 0 — Design only. The website has NOT been built.**

## 1. Goal

A business-first website that presents the platform's insight to a stakeholder/recruiter audience. **Business communication is primary; technical implementation is secondary.**

## 2. Planned Sections

| # | Section | Purpose |
|---|---|---|
| 1 | Executive Overview | Narrative summary of the question, approach, and headline findings. |
| 2 | Business Problem | The business question and why it matters. |
| 3 | Demand Intelligence | Demand patterns, trends, seasonality, volatility. |
| 4 | Forecasting | Forecasts, accuracy, model selection, model honesty. |
| 5 | Inventory Risk | Simulated inventory risk (clearly labeled), stockout/excess signals. |
| 6 | Decision Center | Recommendations and the evidence behind them. |
| 7 | Scenario Analysis | "What-if" comparisons vs baseline. |
| 8 | Methodology | How the analysis is done, end to end. |
| 9 | Architecture | The layered pipeline (see `docs/architecture.md`). |
| 10 | Data Quality | Validation approach and results. |
| 11 | Limitations | Explicit limitations, incl. the no-inventory-in-M5 constraint. |
| 12 | Business Recommendations | Actionable, evidence-backed recommendations. |

## 3. Content & Honesty Requirements

- Every page distinguishes **Observed / Derived / Simulated** data.
- Inventory and scenario figures are labeled **Simulated / Assumption-based**, with the assumption set shown.
- No simulated value is presented as real company data.

## 4. Technical Implementation (secondary, future)

- Static-generated frontend (HTML/CSS/JS or a lightweight framework). No heavy runtime required.
- Data served as prepared static exports/JSON produced by upstream layers.
- Uses the design system tokens from `docs/design_system.md`.
- Responsive (mobile-first), accessible, with loading/error states tested.

## 5. Placement

Web source under `src/web/`, built output under `dist/` (ignored by git). Content authored later from validated Phase 2–3 outputs.
