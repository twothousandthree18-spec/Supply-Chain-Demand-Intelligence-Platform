-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3C - Demand Analysis: derived persistence schema
--
-- These DERIVED tables are populated by src/analytics/run_demand_analysis.py
-- (bounded, resumable). They persist the demand-analysis metrics produced from
-- the Phase 3B materialized layer (mv_weekly_sales, fact_product_store_demand)
-- plus a single bounded day-of-week aggregation.
--
-- Provenance is 'derived'. Observed Phase 2 tables are NOT touched.
-- Formulas & thresholds: docs/demand_analysis.md.
-- ============================================================

-- ---------------------------------------------------------------------------
-- Per-series demand analysis (one row per product x store x window)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_demand_analysis (
    analysis_id          BIGSERIAL PRIMARY KEY,
    product_surr_id      INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id        INT NOT NULL REFERENCES dim_store(store_surr_id),
    analysis_window      TEXT NOT NULL DEFAULT 'observed_full',
    series_start         INT,
    series_end           INT,
    total_units          BIGINT,
    mean_daily_units     NUMERIC(12,4),
    std_daily_units      NUMERIC(12,4),
    cv                   NUMERIC(12,4),
    zero_demand_days     INT,
    zero_demand_ratio    NUMERIC(8,6),
    avg_week_units       NUMERIC(12,4),         -- mean weekly units over active weeks
    recent_4wk_mean      NUMERIC(12,4),         -- mean weekly units, last 4 active weeks
    prior_4wk_mean       NUMERIC(12,4),         -- mean weekly units, 4 weeks before that
    demand_growth_rate   NUMERIC(12,6),         -- recent/prior - 1 (weekly), guarded
    growth_is_defined    BOOLEAN,               -- FALSE when prior denom ~ 0
    growth_denominator_zero BOOLEAN,            -- explicit guard flag
    trend_slope          NUMERIC(16,8),         -- from Phase 3B REGR_SLOPE (daily)
    trend_effect_pct     NUMERIC(12,4),         -- slope * span / mean, as % relative growth
    trend_direction      TEXT,                  -- increasing / flat / decreasing
    seasonality_strength NUMERIC(12,6),         -- CV of monthly seasonal indices
    has_meaningful_seasonality BOOLEAN,
    peak_month           INT,                   -- month with max seasonal index
    trough_month         INT,                   -- month with min seasonal index
    n_active_months      INT,                   -- months with positive weekly demand
    segment_volume       TEXT,                  -- High / Medium / Low
    segment_volatility   TEXT,                  -- High / Medium / Low
    segment_demand       TEXT,                  -- Smooth / Erratic / Lumpy / Intermittent
    risk_cell            TEXT,                  -- e.g. High*High
    risk_category        TEXT,                  -- Critical / High / Moderate / Low
    data_provenance      TEXT NOT NULL DEFAULT 'derived'
        CONSTRAINT chk_danalysis_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    etl_run_id           INT,
    CONSTRAINT uq_demand_analysis UNIQUE (product_surr_id, store_surr_id, analysis_window)
);
COMMENT ON TABLE fact_demand_analysis IS
    'Per-product/store demand-analysis metrics: trend, seasonality, volatility, growth, segmentation, risk. DERIVED (Phase 3C).';

-- ---------------------------------------------------------------------------
-- Calendar seasonality (per series x month); only series with meaningful
-- seasonality are persisted. Index normalized so mean index = 1.00.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_demand_seasonality (
    seasonality_id   BIGSERIAL PRIMARY KEY,
    product_surr_id  INT NOT NULL REFERENCES dim_product(product_surr_id),
    store_surr_id    INT NOT NULL REFERENCES dim_store(store_surr_id),
    analysis_window  TEXT NOT NULL DEFAULT 'observed_full',
    month            INT NOT NULL,              -- 1..12
    seasonality_index NUMERIC(10,6),            -- month mean weekly units / overall mean (>=0)
    obs_weeks        INT,                       -- weeks with units in that month
    is_meaningful    BOOLEAN NOT NULL DEFAULT TRUE,
    data_provenance  TEXT NOT NULL DEFAULT 'derived'
        CONSTRAINT chk_dseas_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    etl_run_id       INT,
    CONSTRAINT uq_demand_seasonality UNIQUE (product_surr_id, store_surr_id, analysis_window, month)
);
COMMENT ON TABLE fact_demand_seasonality IS
    'Calendar (monthly) seasonality indices per product/store week profile. Only meaningful series. DERIVED (Phase 3C).';

-- ---------------------------------------------------------------------------
-- Day-of-week seasonality (weekly pattern) at aggregate scopes.
-- Bounded: one aggregation pass; rows = scopes x 7.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_demand_seasonality_dow (
    dow_id           BIGSERIAL PRIMARY KEY,
    scope_type       TEXT NOT NULL,             -- 'all' | 'store' | 'state' | 'category' | 'dept'
    scope_key        TEXT,                      -- store_id / state_id / category_id / dept_id (NULL for 'all')
    scope_value      TEXT,                      -- human label
    weekday_num      INT NOT NULL,              -- 1..7 (1=Monday in M5)
    weekday_name     TEXT,
    dow_index        NUMERIC(12,6),             -- mean daily units for that DOW / overall daily mean
    obs_days         INT,
    data_provenance  TEXT NOT NULL DEFAULT 'derived'
        CONSTRAINT chk_dow_prov CHECK (data_provenance IN ('observed','derived','simulated')),
    etl_run_id       INT,
    CONSTRAINT uq_dow UNIQUE (scope_type, scope_key, weekday_num)
);
COMMENT ON TABLE fact_demand_seasonality_dow IS
    'Aggregate day-of-week seasonality factors (weekly pattern). Deterministic scope set. DERIVED (Phase 3C).';

-- ---------------------------------------------------------------------------
-- Documented, reproducible thresholds used for segmentation / risk.
-- Written by the Phase 3C driver from src/analytics/config.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demand_analysis_rules (
    rule_id     SERIAL PRIMARY KEY,
    rule_key    TEXT NOT NULL UNIQUE,
    rule_value  NUMERIC(20,10),
    rule_text   TEXT,
    description TEXT
);
COMMENT ON TABLE demand_analysis_rules IS
    'Reproducible thresholds for demand segmentation, volatility classes, intermittency and risk matrix (Phase 3C).';
