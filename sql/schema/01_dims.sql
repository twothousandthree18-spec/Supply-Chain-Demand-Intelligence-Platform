-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - Warehouse Schema: DIMENSIONS
-- Dimension tables per docs/database_architecture.md and docs/erd.md
-- ============================================================

-- Conformed dimension: dim_category
CREATE TABLE IF NOT EXISTS dim_category (
    category_surr_id   SERIAL PRIMARY KEY,          -- surrogate
    category_id        TEXT        NOT NULL UNIQUE,  -- natural key (cat_id), e.g. 'HOBBIES'
    category_name      TEXT        NOT NULL,
    CONSTRAINT chk_category_id CHECK (category_id = upper(category_id))
);
COMMENT ON TABLE dim_category IS 'Conformed product category dimension (FOODS, HOBBIES, HOUSEHOLD). OBSERVED.';

-- Conformed dimension: dim_department
CREATE TABLE IF NOT EXISTS dim_department (
    dept_surr_id  SERIAL PRIMARY KEY,               -- surrogate
    dept_id       TEXT        NOT NULL UNIQUE,      -- natural key (dept_id), e.g. 'HOBBIES_1'
    dept_name     TEXT        NOT NULL,
    category_id   TEXT        NOT NULL,             -- natural reference kept for traceability
    category_surr_id INT      NOT NULL REFERENCES dim_category(category_surr_id)
);
CREATE INDEX IF NOT EXISTS ix_dep_cat ON dim_department(category_surr_id);
COMMENT ON TABLE dim_department IS 'Conformed department dimension; each dept belongs to exactly one category. OBSERVED.';

-- Conformed dimension: dim_store
CREATE TABLE IF NOT EXISTS dim_store (
    store_surr_id SERIAL PRIMARY KEY,              -- surrogate
    store_id      TEXT        NOT NULL UNIQUE,     -- natural key, e.g. 'CA_1'
    state_id      TEXT        NOT NULL,            -- 'CA','TX','WI'
    region_id     TEXT        NOT NULL,            -- 'West','Central','East'
    store_name    TEXT        NOT NULL,
    CONSTRAINT chk_state CHECK (state_id IN ('CA','TX','WI')),
    CONSTRAINT chk_region CHECK (region_id IN ('West','Central','East'))
);
COMMENT ON TABLE dim_store IS 'Conformed store dimension; store->state->region. OBSERVED.';

-- Conformed dimension: dim_product
CREATE TABLE IF NOT EXISTS dim_product (
    product_surr_id SERIAL PRIMARY KEY,            -- surrogate
    product_id      TEXT        NOT NULL UNIQUE,   -- natural key, e.g. 'HOBBIES_1_001'
    item_id         TEXT        NOT NULL,          -- historical M5 item_id (matches sales id prefix)
    dept_id         TEXT        NOT NULL,          -- natural ref
    dept_surr_id    INT         NOT NULL REFERENCES dim_department(dept_surr_id),
    category_id     TEXT        NOT NULL,          -- natural ref
    category_surr_id INT        NOT NULL REFERENCES dim_category(category_surr_id),
    product_label   TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prod_dept ON dim_product(dept_surr_id);
CREATE INDEX IF NOT EXISTS ix_prod_cat  ON dim_product(category_surr_id);
COMMENT ON TABLE dim_product IS 'Conformed product dimension; product->department->category. OBSERVED.';

-- Conformed dimension: dim_date
CREATE TABLE IF NOT EXISTS dim_date (
    date_id        INT  PRIMARY KEY,               -- = M5 day index d_1..d_1969 (surrogate == natural day id)
    calendar_date  DATE NOT NULL UNIQUE,
    day_index      INT  NOT NULL,                  -- M5 day number (1..1969)
    wm_yr_wk       INT  NOT NULL,                  -- Walmart week id
    week_id        INT  NOT NULL,                  -- sequence week ordinal (1..282)
    weekday_num    INT  NOT NULL,                  -- 1..7 (1=Saturday per M5)
    weekday_name   TEXT NOT NULL,
    is_weekend     BOOLEAN NOT NULL,
    month          INT  NOT NULL,
    month_name     TEXT NOT NULL,
    quarter        INT  NOT NULL,
    year           INT  NOT NULL,
    is_event_day   BOOLEAN NOT NULL DEFAULT FALSE,
    event_name_1   TEXT,
    event_type_1   TEXT,
    event_name_2   TEXT,
    event_type_2   TEXT,
    snap_ca        BOOLEAN NOT NULL DEFAULT FALSE,
    snap_tx        BOOLEAN NOT NULL DEFAULT FALSE,
    snap_wi        BOOLEAN NOT NULL DEFAULT FALSE,
    is_observed    BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT chk_date_attrs CHECK (
        year BETWEEN 2000 AND 2030 AND
        month BETWEEN 1 AND 12 AND quarter BETWEEN 1 AND 4
    )
);
COMMENT ON TABLE dim_date IS 'Conformed date dimension. date_id == M5 day index (d_1..). OBSERVED.';

-- Conformed dimension: dim_event
CREATE TABLE IF NOT EXISTS dim_event (
    event_id       SERIAL PRIMARY KEY,
    event_date     DATE   NOT NULL,
    date_id        INT    NOT NULL REFERENCES dim_date(date_id),
    event_name     TEXT   NOT NULL,
    event_type     TEXT   NOT NULL,
    event_ordinal  INT    NOT NULL,                -- 1 or 2 (event_name_1/2 on calendar)
    UNIQUE (event_date, event_name, event_ordinal)
);
CREATE INDEX IF NOT EXISTS ix_event_date ON dim_event(date_id);
COMMENT ON TABLE dim_event IS 'Calendar events extracted from calendar.csv (event_name/type 1 and 2). OBSERVED.';
