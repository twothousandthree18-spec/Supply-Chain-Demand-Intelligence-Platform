-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3A - INDEXES for Phase 3 derived/simulated tables
-- Indexes are justified by representative Phase 3 analytical/forecast/
-- simulation query patterns. Not every column is indexed.
-- ============================================================

-- fact_product_store_demand: small (30,490) and the unique
-- (product_surr_id, store_surr_id, analysis_window) constraint already
-- provides a leading product/store composite. No extra index needed.

-- fact_forecast: filter by entity + origin (validation/final windows),
-- and by model + finality.
CREATE INDEX IF NOT EXISTS ix_ffcast_ent_origin
    ON fact_forecast(product_surr_id, store_surr_id, forecast_origin);
CREATE INDEX IF NOT EXISTS ix_ffcast_model_final
    ON fact_forecast(model_id, is_final);
CREATE INDEX IF NOT EXISTS ix_ffcast_date
    ON fact_forecast(forecast_date);

-- fact_forecast_evaluation: by model (comparison), by entity.
CREATE INDEX IF NOT EXISTS ix_feval_model
    ON fact_forecast_evaluation(model_id);
CREATE INDEX IF NOT EXISTS ix_feval_ent
    ON fact_forecast_evaluation(product_surr_id, store_surr_id);

-- fact_inventory_simulation: by assumption set + entity (simulation run),
-- and by entity + day (time series).
CREATE INDEX IF NOT EXISTS ix_fsim_assump_ent
    ON fact_inventory_simulation(assumption_set_id, product_surr_id, store_surr_id);
CREATE INDEX IF NOT EXISTS ix_fsim_ent_day
    ON fact_inventory_simulation(product_surr_id, store_surr_id, day_id);
