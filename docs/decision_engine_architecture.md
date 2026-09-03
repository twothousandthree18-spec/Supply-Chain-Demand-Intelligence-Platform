# Decision Engine Architecture (Phase 4, Steps 1-3)

**Status:** Contract defined only (Steps 1-3). Decision logic and the production recommendation driver are deferred to a later step.

## Overview

The decision engine translates scenario outputs into **actionable, prioritized recommendations** for each product/store. It is the "last mile" of the scenario engine: after the pure calculators produce per-series metrics, deltas, and risk rankings, the decision engine decides **what to do about it**.

Steps 1-3 deliver the **data contracts** that the decision engine must obey (the `Recommendation` dataclass and the `fact_replenishment_recommendation` table schema). The actual decision logic is a later step.

## Contract: Recommendation

```python
@dataclass(frozen=True)
class Recommendation:
    product_surr_id: int          # which product
    store_surr_id: int            # which store
    decision_day: int             # the simulation day the recommendation applies to
    recommendation: str           # one of 6 action labels (CHECK constraint)
    rationale: str                # human-readable reason
    evidence_fields: dict         # supporting metrics (stockout_days, etc.)
    impact_estimate: str          # qualitative impact description
    traceability_path: str        # which scenarios were compared
    priority: int                 # P1=1, P2=2, P3=3, P4=4
    priority_label: str           # "P1", "P2", "P3", "P4"
    scenario_id: int              # FK to scenario.scenario_id
    scenario_run_id: int          # FK to fact_scenario_run.scenario_run_id
    assumption_set_id: int        # FK to assumption_set.assumption_set_id
    data_provenance: str          # always "simulated"
```

## Recommendation Action Labels

The `recommendation` field is constrained by a DB CHECK constraint to exactly these values:

| Label | When It Applies |
|-------|----------------|
| `REORDER` | Series is below reorder point or has projected stockout risk |
| `MONITOR` | Series is within normal parameters but needs attention |
| `REDUCE INVENTORY` | Series has excess inventory above the 28-day ceiling |
| `HIGH STOCKOUT RISK` | Stockout risk ranking flagged the series as High/Critical |
| `EXCESS INVENTORY` | Excess inventory risk ranking flagged the series as High/Critical |
| `NO ACTION REQUIRED` | Series is in a healthy state with no flags |

## Priority Labels

| Priority | Label | Meaning |
|----------|-------|---------|
| 1 | P1 | Immediate action required |
| 2 | P2 | Action required within this planning cycle |
| 3 | P3 | Action required within the next planning cycle |
| 4 | P4 | No immediate action; monitor |

## DB Schema

The `fact_replenishment_recommendation` table was created in Phase 2 (structure-only, always empty). Phase 4 adds four columns via ALTER:

```sql
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN scenario_id      INT;   -- FK to scenario.scenario_id
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN scenario_run_id  INT;   -- FK to fact_scenario_run.scenario_run_id
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN priority         INT;   -- P1=1, P2=2, P3=3, P4=4
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN priority_label   TEXT;  -- "P1", "P2", "P3", "P4"
```

This is additive — no existing Phase 2-3E data is modified. The table remains empty until the decision-engine driver runs in a later step.

## Indexes

```sql
CREATE INDEX ix_rec_scenario
    ON fact_replenishment_recommendation(scenario_run_id)
    WHERE scenario_run_id IS NOT NULL;

CREATE INDEX ix_rec_ent_decision
    ON fact_replenishment_recommendation(product_surr_id, store_surr_id, decision_day);
```

## Decision Logic (deferred)

The decision engine will:
1. Read `ScenarioSeriesResult` rows from `fact_scenario_result`.
2. Apply the risk ranking (scenarios 5/6) to produce per-series scores.
3. Cross-reference the baseline vs scenario deltas.
4. Map scores + deltas to one of the 6 action labels.
5. Assign priority (P1-P4) based on risk tier + urgency.
6. Emit `Recommendation` objects for each series that needs action.
7. Persist them to `fact_replenishment_recommendation` with full traceability.

This is the **only step that touches the recommendation table** — it is not part of Steps 1-3.

## Traceability

Every recommendation carries:
- `scenario_id` — which scenario definition produced it
- `scenario_run_id` — which execution run produced it
- `assumption_set_id` — which assumption set was used
- `traceability_path` — human-readable chain (e.g., "baseline -> demand_shock_p20")
- `evidence_fields` — supporting metrics (stockout_days, delta_stockout_units, etc.)

This ensures every recommendation can be traced back to the exact inputs and parameters that produced it.
