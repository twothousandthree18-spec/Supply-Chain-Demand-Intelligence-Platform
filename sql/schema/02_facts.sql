-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - Warehouse Schema: FACT TABLES
-- Per docs/database_architecture.md and docs/erd.md
-- ============================================================

-- ============================================================
-- OBSERVED facts (populated in Phase 2)
-- ============================================================

-- fact_daily_sales: grain = 1 row per (product, store, day)
CREATE TABLE IF NOT EXISTS fact_daily_sales (
    sales_id     BIGSERIAL PRIMARY KEY,
    product_surr_id INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id   INT NOT NULL REFERENCES dim_store(store_surr_id),
    date_id         INT NOT NULL REFERENCES dim_date(date_id),
    units_sold      INT NOT NULL,                   -- observed demand proxy
    demand_source   TEXT NOT NULL DEFAULT 'eval',   -- observed set origin
    data_provenance TEXT NOT NULL DEFAULT 'observed',
    etl_run_id      INT,
    CONSTRAINT chk_sales_units CHECK (units_sold >= 0),
    CONSTRAINT chk_sales_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    UNIQUE (product_surr_id, store_surr_id, date_id)
);
COMMENT ON TABLE fact_daily_sales IS 'Observed daily unit sales. grain=(product,store,date). units_sold is the observed demand proxy.';

-- fact_weekly_price: grain = 1 row per (product, store, week)
CREATE TABLE IF NOT EXISTS fact_weekly_price (
    price_id     BIGSERIAL PRIMARY KEY,
    product_surr_id INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id   INT NOT NULL REFERENCES dim_store(store_surr_id),
    wm_yr_wk        INT NOT NULL,                   -- natural week key; maps to dim_date.wm_yr_wk
    week_id         INT NOT NULL,                   -- ordered week ordinal (matches dim_date)
    sell_price      NUMERIC(10,2) NOT NULL,
    data_provenance TEXT NOT NULL DEFAULT 'observed',
    etl_run_id      INT,
    CONSTRAINT chk_price_amt CHECK (sell_price >= 0),
    CONSTRAINT chk_price_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    UNIQUE (product_surr_id, store_surr_id, wm_yr_wk)
);
COMMENT ON TABLE fact_weekly_price IS 'Observed weekly selling price. grain=(product,store,week).';

-- ============================================================
-- DERIVED / SIMULATED facts (STRUCTURE ONLY in Phase 2;
-- populated in later phases per the Phase 0 architecture)
-- ============================================================

-- fact_product_store_demand: grain=(product,store) demand statistics (DERIVED)
CREATE TABLE IF NOT EXISTS fact_product_store_demand (
    demand_stat_id BIGSERIAL PRIMARY KEY,
    product_surr_id INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id   INT NOT NULL REFERENCES dim_store(store_surr_id),
    analysis_window TEXT NOT NULL,
    series_start    INT NOT NULL,
    series_end      INT NOT NULL,
    total_units     BIGINT NOT NULL,
    mean_daily_units NUMERIC(12,4),
    std_daily_units  NUMERIC(12,4),
    cv               NUMERIC(12,4),
    zero_demand_days INT,
    demand_growth_rate NUMERIC(12,6),
    trend_slope      NUMERIC(16,8),
    data_provenance  TEXT NOT NULL DEFAULT 'derived',
    CONSTRAINT chk_ddemand_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    UNIQUE (product_surr_id, store_surr_id, analysis_window)
);
COMMENT ON TABLE fact_product_store_demand IS 'Derived demand statistics per product/store. STRUCTURE ONLY in Phase 2.';

-- fact_forecast (DERIVED) - populated in forecasting phase
CREATE TABLE IF NOT EXISTS fact_forecast (
    forecast_id    BIGSERIAL PRIMARY KEY,
    model_id       INT NOT NULL,                   -- FK to model_registry
    product_surr_id INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id   INT NOT NULL REFERENCES dim_store(store_surr_id),
    forecast_origin INT NOT NULL,                  -- day index of forecast origin
    forecast_horizon INT NOT NULL,
    forecast_date    INT NOT NULL,                 -- day index being forecast
    forecast_value   NUMERIC(14,4) NOT NULL,
    lower_bound      NUMERIC(14,4),
    upper_bound      NUMERIC(14,4),
    is_final         BOOLEAN NOT NULL DEFAULT FALSE,
    data_provenance  TEXT NOT NULL DEFAULT 'derived',
    CONSTRAINT chk_fcast_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_forecast IS 'Derived forecasts. STRUCTURE ONLY in Phase 2.';

-- fact_forecast_evaluation (DERIVED) - populated in forecasting phase
CREATE TABLE IF NOT EXISTS fact_forecast_evaluation (
    eval_id          BIGSERIAL PRIMARY KEY,
    model_id         INT NOT NULL,                 -- FK to model_registry
    product_surr_id  INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id    INT NOT NULL REFERENCES dim_store(store_surr_id),
    validation_start INT NOT NULL,
    validation_end   INT NOT NULL,
    mae   NUMERIC(16,6), rmse  NUMERIC(16,6),
    wmae  NUMERIC(16,6), wrmse NUMERIC(16,6),
    abs_error NUMERIC(16,6),
    bias      NUMERIC(16,6),
    data_provenance TEXT NOT NULL DEFAULT 'derived',
    CONSTRAINT chk_feval_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_forecast_evaluation IS 'Derived forecast evaluation. STRUCTURE ONLY in Phase 2.';

-- fact_inventory_simulation (SIMULATED) - populated in inventory phase
CREATE TABLE IF NOT EXISTS fact_inventory_simulation (
    sim_id             BIGSERIAL PRIMARY KEY,
    assumption_set_id  INT NOT NULL,               -- FK to assumption_set
    product_surr_id    INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id      INT NOT NULL REFERENCES dim_store(store_surr_id),
    day_id             INT NOT NULL,
    starting_inventory NUMERIC(14,4),
    demand_forecast    NUMERIC(14,4),
    lead_time_demand   NUMERIC(14,4),
    safety_stock       NUMERIC(14,4),
    reorder_point      NUMERIC(14,4),
    inventory_position NUMERIC(14,4),
    on_hand            NUMERIC(14,4),
    orders_placed      NUMERIC(14,4),
    reorder_qty        NUMERIC(14,4),
    projected_stockout BOOLEAN NOT NULL DEFAULT FALSE,
    stockout_units     NUMERIC(14,4),
    excess_inventory   NUMERIC(14,4),
    days_of_inventory  NUMERIC(14,4),
    service_level_achieved NUMERIC(8,6),
    data_provenance    TEXT NOT NULL DEFAULT 'simulated',
    CONSTRAINT chk_sim_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_inventory_simulation IS 'Simulated inventory positions. STRUCTURE ONLY in Phase 2.';

-- fact_replenishment_recommendation (SIMULATED/DERIVED) - populated in decision phase
CREATE TABLE IF NOT EXISTS fact_replenishment_recommendation (
    rec_id             BIGSERIAL PRIMARY KEY,
    assumption_set_id  INT NOT NULL,               -- FK to assumption_set
    product_surr_id    INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id      INT NOT NULL REFERENCES dim_store(store_surr_id),
    decision_day       INT NOT NULL,
    recommendation     TEXT NOT NULL,
    rationale          TEXT,
    evidence_fields    JSONB,
    impact_estimate    TEXT,
    traceability_path  TEXT,
    data_provenance    TEXT NOT NULL DEFAULT 'simulated',
    CONSTRAINT chk_rec_opt CHECK (
        recommendation IN ('REORDER','MONITOR','REDUCE INVENTORY','HIGH STOCKOUT RISK','EXCESS INVENTORY','NO ACTION REQUIRED')),
    CONSTRAINT chk_rec_prov CHECK (data_provenance IN ('observed','derived','simulated'))
);
COMMENT ON TABLE fact_replenishment_recommendation IS 'Decision-engine recommendations. STRUCTURE ONLY in Phase 2.';
