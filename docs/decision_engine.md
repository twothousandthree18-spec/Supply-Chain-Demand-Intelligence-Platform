# Decision Engine — Design

**Phase 0 — Design only. No recommendations have been generated.**

## 1. Purpose

Convert analytical evidence into explicit, traceable operational recommendations.

## 2. Recommendation Framework

Every output follows the structure:

```
PROBLEM
  → EVIDENCE
  → IMPACT
  → RECOMMENDED ACTION
```

- **PROBLEM** — the operational condition identified (e.g., projected stockout).
- **EVIDENCE** — the specific observed/derived/simulated figures that support it (forecast, safety stock, inventory position, lead time, service level).
- **IMPACT** — the expected business consequence (lost sales/stockout, holding/excess cost, service-level breach).
- **RECOMMENDED ACTION** — the explicit action to take.

## 3. Planned Recommendation Outputs

| Recommendation | Typical trigger (evidence) |
|---|---|
| **REORDER** | projected inventory falls below reorder point before next replenishment; stockout risk high. |
| **MONITOR** | approaching reorder point but short-term coverage adequate; watch. |
| **REDUCE INVENTORY** | on-hand exceeds coverage target and/or excess inventory high; demand declining. |
| **HIGH STOCKOUT RISK** | projected stockout probability above threshold given service level. |
| **EXCESS INVENTORY** | days-of-inventory far above target over the horizon. |
| **NO ACTION REQUIRED** | position healthy; no projected issue. |

## 4. Mathematical Traceability

Every recommendation MUST be traceable to source/derived data:

- Each action stores an `evidence_fields` JSON and a `traceability_path` describing exactly which metric(s) and thresholds produced the decision (e.g., `projected_on_hand[+6d] < reorder_point` ⇒ `REORDER`).
- Thresholds (service level, coverage targets, stockout-risk tolerance) are configurable in the `assumption_set`.
- Outputs are written to `fact_replenishment_recommendation` with their assumption/scenario IDs and `data_provenance`.

## 5. Determinism & Testability

- Rules are deterministic functions of validated inputs, so they are unit-testable (see `docs/testing_strategy.md` → Decision tests).
- Changing thresholds re-evaluates all entities, keeping the whole decision output reproducible.

## 6. Presentation

Recommendations power the "Action Center" and "Scenario Analysis" dashboard/web sections, always alongside the evidence and the classification of data as Observed / Derived / Simulated.
