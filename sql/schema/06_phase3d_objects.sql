-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3D - Forecasting: governance + derived persistence DDL
--
-- Extends the Phase 2/3A structure for the forecasting layer:
--   * model_registry            - forecasting governance (metrics, period,
--                                 provenance, selection status)
--   * fact_forecast             - derived product/store/day forecasts
--   * fact_forecast_evaluation  - realized chronological-holdout metrics
--   * forecast_rules            - documented, reproducible thresholds
--
-- These objects are populated by src/forecasting/run_forecasting.py
-- (bounded, resumable). Provenance is 'derived'. Observed Phase 2 tables
-- are NOT touched.
-- Formulas & definitions: docs/forecasting_architecture.md.
-- ============================================================

-- ---------------------------------------------------------------------------
-- model_registry: add forecasting-governance columns (idempotent)
-- ---------------------------------------------------------------------------
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS training_start    INT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS training_end      INT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS validation_start  INT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS validation_end    INT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS metrics_json      JSONB;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS selection_rationale TEXT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS data_provenance   TEXT NOT NULL DEFAULT 'derived';
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS etl_run_id        INT;

-- ---------------------------------------------------------------------------
-- fact_forecast: add audit run id + supporting indexes
-- ---------------------------------------------------------------------------
ALTER TABLE fact_forecast ADD COLUMN IF NOT EXISTS etl_run_id INT;

CREATE INDEX IF NOT EXISTS ix_fcast_series_date ON fact_forecast(product_surr_id, store_surr_id, forecast_date);
CREATE INDEX IF NOT EXISTS ix_fcast_model ON fact_forecast(model_id);

-- ---------------------------------------------------------------------------
-- fact_forecast_evaluation: add audit run id + holdout size + indexes
-- ---------------------------------------------------------------------------
ALTER TABLE fact_forecast_evaluation ADD COLUMN IF NOT EXISTS etl_run_id INT;
ALTER TABLE fact_forecast_evaluation ADD COLUMN IF NOT EXISTS n_holdout INT;

CREATE INDEX IF NOT EXISTS ix_feval_series_model ON fact_forecast_evaluation(product_surr_id, store_surr_id, model_id);
CREATE INDEX IF NOT EXISTS ix_feval_model ON fact_forecast_evaluation(model_id);

-- ---------------------------------------------------------------------------
-- Documented, reproducible forecasting thresholds/rule constants.
-- Written by the Phase 3D driver from src/forecasting/config.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecast_rules (
    rule_id     SERIAL PRIMARY KEY,
    rule_key    TEXT NOT NULL UNIQUE,
    rule_value  NUMERIC(20,10),
    rule_text   TEXT,
    description TEXT
);
COMMENT ON TABLE forecast_rules IS
    'Reproducible forecasting thresholds: horizon, validation split, MA window, intervals, model-selection rule. DERIVED (Phase 3D).';
