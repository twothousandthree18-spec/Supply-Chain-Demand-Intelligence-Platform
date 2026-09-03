-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - Warehouse Schema: METADATA / CONFIGURATION TABLES
-- Per docs/database_architecture.md
-- ============================================================

-- Assumption set configuration (used by simulation/scenario/decision phases)
CREATE TABLE IF NOT EXISTS assumption_set (
    assumption_set_id SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    starting_inventory_rule  TEXT,
    supplier_lead_time_days  NUMERIC(8,2),
    service_level            NUMERIC(8,6),
    safety_stock_formula     TEXT,
    reorder_policy           TEXT,
    reorder_quantity_rule    TEXT,
    demand_adjustment        NUMERIC(8,6) DEFAULT 1.0,  -- 1.0 = no adjustment
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE assumption_set IS 'Configurable operational assumptions for simulation/scenario/decision phases (Phase 3+).';

-- ETL run log (audit)
CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id            SERIAL PRIMARY KEY,
    pipeline          TEXT NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL,                -- running | success | failed
    records_processed BIGINT,
    records_loaded    BIGINT,
    checksum_manifest TEXT,
    error_message     TEXT
);
COMMENT ON TABLE etl_run_log IS 'Audit log of every ETL run.';

-- Data quality results (validation output)
CREATE TABLE IF NOT EXISTS data_quality_results (
    result_id    SERIAL PRIMARY KEY,
    run_id       INT REFERENCES etl_run_log(run_id),
    check_name   TEXT NOT NULL,
    table_name   TEXT,
    column_name  TEXT,
    severity     TEXT NOT NULL,                     -- error | warning | info
    status       TEXT NOT NULL,                     -- pass | fail | warn
    metric_value NUMERIC,
    details      TEXT,
    checked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE data_quality_results IS 'Results of database integrity/quality checks.';

-- Model registry (forecasting phase)
CREATE TABLE IF NOT EXISTS model_registry (
    model_id          SERIAL PRIMARY KEY,
    model_name        TEXT NOT NULL,
    model_family      TEXT NOT NULL,
    params_json       JSONB,
    training_window   TEXT,
    validation_method TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    git_ref           TEXT,
    is_selected       BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE model_registry IS 'Registry of forecasting models. STRUCTURE ONLY in Phase 2.';
