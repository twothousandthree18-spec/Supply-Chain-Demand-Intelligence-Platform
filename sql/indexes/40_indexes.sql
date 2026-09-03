-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - INDEXES
-- Indexes justified by representative analytical query patterns
-- (see Phase 2 report, §Performance). Not every column is indexed.
-- ============================================================

-- fact_daily_sales: unique constraint (product,store,date_id) already
-- provides a leading-composite index for (product,store,date) paths.
-- Add single-column selectivity/grouping indexes used frequently.
CREATE INDEX IF NOT EXISTS ix_fds_date   ON fact_daily_sales(date_id);
CREATE INDEX IF NOT EXISTS ix_fds_store  ON fact_daily_sales(store_surr_id);
CREATE INDEX IF NOT EXISTS ix_fds_product ON fact_daily_sales(product_surr_id);

-- fact_weekly_price: unique (product,store,wm_yr_wk) exists; add week filter.
CREATE INDEX IF NOT EXISTS ix_fwp_week ON fact_weekly_price(week_id);
CREATE INDEX IF NOT EXISTS ix_fwp_product ON fact_weekly_price(product_surr_id);
CREATE INDEX IF NOT EXISTS ix_fwp_store ON fact_weekly_price(store_surr_id);

-- weather/supporting joins
CREATE INDEX IF NOT EXISTS ix_dd_date ON dim_date(calendar_date);
CREATE INDEX IF NOT EXISTS ix_dp_item ON dim_product(item_id);
