-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 4 - Scenario Engine & Decision Intelligence: DDL
--
-- Adds the scenario/decision persistence layer ON TOP of the completed
-- Phase 2/3B/3C/3D/3E objects. It consumes existing outputs only:
--   * fact_demand_analysis        (Phase 3C sizing moments)
--   * fact_forecast is_final      (Phase 3D forecast demand)
--   * assumption_set (id=1)       (Phase 3E baseline assumptions)
-- and reuses the existing inventory policy/engine. No Phase 2-3E table is
-- re-populated or altered except the UNPOPULATED (structure-only) decision
-- sink fact_replenishment_recommendation, which gains scenario linking and
-- priority columns.
--
-- Metadata objects (written by the Phase 4 driver, idempotent):
--   * scenario                      - scenario definitions (contract)
--   * scenario_rules                - reproducible thresholds/weights
-- Fact objects (populated by bounded, batched scenario runs):
--   * fact_scenario_run             - one row per scenario execution
--   * fact_scenario_result          - per-series scenario metrics/deltas/risk
--   * fact_scenario_comparison      - aggregate comparison/trade-off per run
-- Decision sink (structure exists from Phase 2):
--   * fact_replenishment_recommendation (ALTERed: scenario ids + priority)
--
-- Provenance: every scenario/decision output is 'simulated'.
-- ============================================================

-- ---------------------------------------------------------------------------
-- scenario definitions (metadata / versioned configuration)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario (
    scenario_id          SERIAL PRIMARY KEY,
    scenario_name        TEXT NOT NULL UNIQUE,
    scenario_type        TEXT NOT NULL,
    params_json          JSONB NOT NULL DEFAULT '{}',
    base_assumption_set_id INT NOT NULL REFERENCES assumption_set(assumption_set_id),
    description          TEXT,
    version              INT NOT NULL DEFAULT 1,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_scen_type CHECK (scenario_type IN
        ('baseline','demand_shock','lead_time_change','service_level_change','reorder_policy',
         'stockout_risk_prioritization','excess_inventory_prioritization','action_tradeoff')),
    CONSTRAINT chk_scen_version CHECK (version >= 1)
);
COMMENT ON TABLE scenario IS
    'Scenario definitions (name/type/params/base assumption set). SIMULATED provenance. Phase 4.';

-- Idempotent upgrade: ensure 'baseline' is a valid scenario_type on already
-- created tables (DROP+ADD re-adds the identical allowlist, now incl. baseline).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'scenario'
          AND c.conname = 'chk_scen_type'
          AND pg_get_constraintdef(c.oid) LIKE '%baseline%'
    ) THEN
        ALTER TABLE scenario DROP CONSTRAINT chk_scen_type;
        ALTER TABLE scenario ADD CONSTRAINT chk_scen_type CHECK (scenario_type IN
            ('baseline','demand_shock','lead_time_change','service_level_change','reorder_policy',
             'stockout_risk_prioritization','excess_inventory_prioritization','action_tradeoff'));
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- scenario run header (one row per execution; versioned + reproducible)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_scenario_run (
    scenario_run_id      SERIAL PRIMARY KEY,
    scenario_id          INT NOT NULL REFERENCES scenario(scenario_id),
    assumption_set_id    INT NOT NULL REFERENCES assumption_set(assumption_set_id),
    executed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status               TEXT NOT NULL DEFAULT 'running',
    records_processed    BIGINT,
    reproducibility      JSONB,              -- input snapshots + effective params
    data_provenance      TEXT NOT NULL DEFAULT 'simulated',
    etl_run_id           INT,
    CONSTRAINT chk_scen_run_status CHECK (status IN ('running','success','failed')),
    CONSTRAINT chk_scen_run_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_scenario_run IS
    'Scenario execution header (1 row per run; deterministic, reproducible). SIMULATED. Phase 4.';

-- ---------------------------------------------------------------------------
-- per-series scenario results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_scenario_result (
    scenario_result_id   BIGSERIAL PRIMARY KEY,
    scenario_run_id      INT NOT NULL REFERENCES fact_scenario_run(scenario_run_id),
    product_surr_id      INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id        INT NOT NULL REFERENCES dim_store(store_surr_id),
    -- policy / sizing snapshot (assumption-set values used by this scenario)
    expected_daily_demand  NUMERIC(12,4),
    daily_sigma            NUMERIC(12,4),
    cv                     NUMERIC(12,4),
    total_units_hist       NUMERIC(16,2),
    safety_stock           NUMERIC(14,4),
    reorder_point          NUMERIC(14,4),
    reorder_qty            NUMERIC(14,4),
    starting_inventory     NUMERIC(14,4),
    lead_time_days         NUMERIC(8,2),
    service_level_target   NUMERIC(8,6),
    -- demand
    total_demand           NUMERIC(16,4),
    -- service / stockout
    stockout_days          INT,
    stockout_units         NUMERIC(16,4),
    service_level_achieved NUMERIC(8,6),
    fill_rate              NUMERIC(8,6),
    -- reorder activity
    reorder_frequency      INT,
    total_reorder_units    NUMERIC(16,4),
    replenishment_units    NUMERIC(16,4),
    -- inventory
    avg_inventory_position NUMERIC(16,4),
    avg_on_hand            NUMERIC(16,4),
    final_on_hand          NUMERIC(16,4),
    final_on_order         NUMERIC(16,4),
    final_backorder        NUMERIC(16,4),
    -- excess
    excess_days            INT,
    total_excess_units     NUMERIC(16,4),
    avg_days_of_inventory  NUMERIC(16,4),
    -- ranking (populated for stockout/excess prioritization scenarios)
    risk_score             NUMERIC(10,6),
    risk_tier              TEXT,
    risk_rank              INT,
    risk_components        JSONB,
    -- deltas versus the scenario's baseline run
    delta_stockout_days           INT,
    delta_stockout_units          NUMERIC(16,4),
    delta_service_level           NUMERIC(8,6),
    delta_fill_rate               NUMERIC(8,6),
    delta_reorder_frequency       INT,
    delta_total_reorder_units     NUMERIC(16,4),
    delta_avg_inventory_position  NUMERIC(16,4),
    delta_excess_days             INT,
    delta_total_excess_units      NUMERIC(16,4),
    delta_avg_days_of_inventory   NUMERIC(16,4),
    data_provenance          TEXT NOT NULL DEFAULT 'simulated',
    CONSTRAINT uq_scenario_result UNIQUE (scenario_run_id, product_surr_id, store_surr_id),
    CONSTRAINT chk_scen_res_rank CHECK (risk_rank IS NULL OR risk_rank >= 1),
    CONSTRAINT chk_scen_res_tier CHECK (risk_tier IS NULL OR
        risk_tier IN ('Low','Medium','High','Critical')),
    CONSTRAINT chk_scen_res_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_scenario_result IS
    'Per-series scenario simulation/output metrics (+ deltas + risk ranking). SIMULATED. Phase 4.';

-- ---------------------------------------------------------------------------
-- aggregate comparison / trade-off per scenario run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_scenario_comparison (
    comparison_id          BIGSERIAL PRIMARY KEY,
    scenario_run_id        INT NOT NULL REFERENCES fact_scenario_run(scenario_run_id),
    baseline_scenario_run_id INT,             -- NULL for the baseline run itself
    aggregate_json         JSONB,             -- aggregate KPIs + trade-off
    n_series               INT,
    horizon_days           INT,
    data_provenance        TEXT NOT NULL DEFAULT 'simulated',
    CONSTRAINT uq_scenario_comparison UNIQUE (scenario_run_id),
    CONSTRAINT chk_scen_cmp_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_scenario_comparison IS
    'Aggregate scenario-vs-baseline comparison (trade-off) per scenario run. SIMULATED. Phase 4.';

-- ---------------------------------------------------------------------------
-- reproducible scenario thresholds/weights (written from config.py)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario_rules (
    rule_id     SERIAL PRIMARY KEY,
    rule_key    TEXT NOT NULL UNIQUE,
    rule_value  NUMERIC(20,10),
    rule_text   TEXT,
    description TEXT
);
COMMENT ON TABLE scenario_rules IS
    'Reproducible scenario thresholds/weights: horizon, bounds, ranking weights, tiers. Phase 4.';

-- ---------------------------------------------------------------------------
-- decision sink: extend the Phase 2 STRUCTURE-ONLY recommendation table with
-- scenario linking + priority (table is empty; no Phase 2 data is modified)
-- ---------------------------------------------------------------------------
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN IF NOT EXISTS scenario_id      INT;
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN IF NOT EXISTS scenario_run_id  INT;
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN IF NOT EXISTS priority         INT;
ALTER TABLE fact_replenishment_recommendation
    ADD COLUMN IF NOT EXISTS priority_label   TEXT;