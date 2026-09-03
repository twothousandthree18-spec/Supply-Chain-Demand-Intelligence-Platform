# Testing Strategy

**Phase 0 — Design only. No tests have been implemented.**

## 1. Purpose

Guarantee correctness, reproducibility, and honesty across every layer. Each layer's tests prevent silent errors from cascading to decisions.

## 2. Planned Test Layers

### DATA TESTS (`tests/data/`)
- **Schema:** columns, dtypes, expected codes present.
- **Duplicates:** no duplicate (product, store, date) records in facts.
- **Nulls:** required fields non-null; null rates within tolerance.
- **Invalid relationships:** every FK resolves; product→store→region consistency; no orphan keys.
- **Date continuity:** no missing dates within the observed span; calendar completeness.

### SQL TESTS (`tests/sql/`)
- **KPI correctness:** each KPI matches its canonical definition.
- **Aggregation correctness:** rollups (daily→weekly→monthly; product→category→dept; store→region) reconcile with base facts.
- **Analytical-view validation:** views return expected row counts and invariant relationships (e.g., totals additive).

### PYTHON TESTS (`tests/python/`)
- **Feature calculations:** derived features match reference computations.
- **Metrics:** MAE/RMSE/WMAE/WRMSE/bias/safety-stock formulas verified against hand-computed values.
- **Forecast inputs/outputs:** clean in/out contract; no NaN/Inf; shapes correct.
- **Inventory calculations:** simulation step logic (position, reorder point, stockout) unit-tested.

### FORECAST TESTS (`tests/forecast/`)
- **Leakage detection:** no future info in training features.
- **Chronological validation:** holdout is always past→future; random split rejected.
- **Reproducibility:** same seed/config ⇒ identical outputs.

### DECISION TESTS (`tests/decision/`)
- **Reorder logic:** boundary cases (just above/below reorder point).
- **Risk logic:** stockout/excess thresholds behavior.
- **Scenario calculations:** scenario deltas correctly transform baseline.

### UI TESTS (`tests/ui/`)
- **Responsive behavior:** layouts at key breakpoints.
- **Visual integrity:** design tokens applied; no off-palette colors.
- **Accessibility:** contrast, headings, keyboard, ARIA basics.
- **Broken links:** internal navigation resolves.
- **Loading/error states:** empty/error datasets render gracefully (no blank pages).

## 3. Tooling (future)

- **pytest** for Python/data/forecast/decision/business-logic tests.
- **PostgreSQL** for SQL view-validation harness (assert expected counts/metrics).
- Lightweight UI test runner (e.g., Playwright or equivalent) in a later phase.

## 4. CI / Repeatability (future)

- A single command runs the full test suite against fixtures.
- Data fixtures are small, curated, reproducible samples — minimal but representative.
- Tests gate progress between phases (e.g., no forecasting before warehouse tests pass).
