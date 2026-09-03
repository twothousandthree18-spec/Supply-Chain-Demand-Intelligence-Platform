-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3A - Foundation: derived/simulated fact referential integrity
--
-- The Phase 3 derived/simulated fact tables were created STRUCTURE-ONLY in
-- Phase 2 (sql/schema/02_facts.sql) with their governance keys as plain INT.
-- Phase 3A enforces the intended referential integrity modeled in
-- docs/database_architecture.md:
--   fact_forecast            -n--1 model_registry
--   fact_forecast_evaluation -n--1 model_registry
--   fact_inventory_simulation -n--1 assumption_set
--
-- All Phase 3 fact tables are currently EMPTY, so these additions are instant
-- and safe. They are idempotent (a constraint is only added when absent) and
-- never touch the observed fact tables.
-- ============================================================

-- fact_forecast.model_id -> model_registry
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_fcast_model'
    ) THEN
        ALTER TABLE fact_forecast
            ADD CONSTRAINT fk_fcast_model
            FOREIGN KEY (model_id) REFERENCES model_registry(model_id);
    END IF;
END;
$$ LANGUAGE plpgsql;

-- fact_forecast_evaluation.model_id -> model_registry
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_feval_model'
    ) THEN
        ALTER TABLE fact_forecast_evaluation
            ADD CONSTRAINT fk_feval_model
            FOREIGN KEY (model_id) REFERENCES model_registry(model_id);
    END IF;
END;
$$ LANGUAGE plpgsql;

-- fact_inventory_simulation.assumption_set_id -> assumption_set
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_sim_assumption'
    ) THEN
        ALTER TABLE fact_inventory_simulation
            ADD CONSTRAINT fk_sim_assumption
            FOREIGN KEY (assumption_set_id) REFERENCES assumption_set(assumption_set_id);
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE fact_product_store_demand IS
    'Derived demand statistics per product/store. Populated in Phase 3C.';
COMMENT ON TABLE fact_forecast IS
    'Derived forecasts. Populated in Phase 3D/3E.';
COMMENT ON TABLE fact_forecast_evaluation IS
    'Derived forecast evaluation. Populated in Phase 3E.';
COMMENT ON TABLE fact_inventory_simulation IS
    'Simulated inventory positions. Populated in Phase 3G.';
