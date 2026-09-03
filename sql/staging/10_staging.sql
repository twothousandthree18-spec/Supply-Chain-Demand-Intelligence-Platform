-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - STAGING TABLES
-- Source-shaped staging layer. These hold raw file data before
-- transformation into the warehouse model. RAW files stay immutable.
-- ============================================================

-- calendar.csv staging (source-shaped)
CREATE TABLE IF NOT EXISTS stg_calendar (
    d             TEXT NOT NULL,          -- 'd_1'...
    date          DATE NOT NULL,
    wm_yr_wk      INT NOT NULL,
    weekday       TEXT NOT NULL,
    wday          INT NOT NULL,
    month         INT NOT NULL,
    year          INT NOT NULL,
    event_name_1  TEXT,
    event_type_1  TEXT,
    event_name_2  TEXT,
    event_type_2  TEXT,
    snap_ca       INT NOT NULL,
    snap_tx       INT NOT NULL,
    snap_wi       INT NOT NULL
);

-- sell_prices.csv staging (source-shaped)
CREATE TABLE IF NOT EXISTS stg_sell_prices (
    store_id    TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    wm_yr_wk    INT NOT NULL,
    sell_price  NUMERIC(10,2) NOT NULL
);

-- long-form daily sales staging (produced by ETL from wide sales CSV)
CREATE TABLE IF NOT EXISTS stg_sales_daily (
    id        TEXT NOT NULL,
    item_id   TEXT NOT NULL,
    store_id  TEXT NOT NULL,
    day_index INT NOT NULL,
    units     INT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_stg_sales_day ON stg_sales_daily(day_index);

-- product/store hierarchy metadata staging (loaded from sales id columns;
-- small: 30,490 rows). Drives category/department/product/store dimensions.
CREATE TABLE IF NOT EXISTS stg_sales_meta (
    id       TEXT NOT NULL,
    item_id  TEXT NOT NULL,
    dept_id  TEXT NOT NULL,
    cat_id   TEXT NOT NULL,
    store_id TEXT NOT NULL,
    state_id TEXT NOT NULL
);
