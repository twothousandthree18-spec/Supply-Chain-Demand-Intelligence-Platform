-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 4 - INDEXES for the scenario/decision layer
-- Justified by bounded scenario reads (per-series pulls, ranking queries,
-- per-run comparisons). Not every column is indexed.
-- ============================================================

-- fact_scenario_run: list recent runs of a scenario.
CREATE INDEX IF NOT EXISTS ix_scen_run_scen_exec
    ON fact_scenario_run(scenario_id, executed_at);

-- fact_scenario_result: entity lookup across runs, and ranking scans.
CREATE INDEX IF NOT EXISTS ix_scen_res_run
    ON fact_scenario_result(scenario_run_id);
CREATE INDEX IF NOT EXISTS ix_scen_res_ent
    ON fact_scenario_result(product_surr_id, store_surr_id);
CREATE INDEX IF NOT EXISTS ix_scen_res_rank
    ON fact_scenario_result(scenario_run_id, risk_rank)
    WHERE risk_rank IS NOT NULL;

-- fact_scenario_comparison: unique (scenario_run_id) already covers lookups.

-- fact_replenishment_recommendation: per-scenario decision output (Phase 4).
CREATE INDEX IF NOT EXISTS ix_rec_scenario
    ON fact_replenishment_recommendation(scenario_run_id)
    WHERE scenario_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_rec_ent_decision
    ON fact_replenishment_recommendation(product_surr_id, store_surr_id, decision_day);