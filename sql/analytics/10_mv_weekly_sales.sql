-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3B - SQL Analytical Layer
-- 10_mv_weekly_sales.sql : materialized weekly revenue anchor
--
-- WHY THIS IS THE ANCHOR:
--   Price is constant within a week per (product, store), and daily units are
--   additive. Revenue is therefore well-defined once at the WEEKLY grain:
--       revenue(week) = units(week) * sell_price(week)
--   and is additive to every higher grain (month / quarter / year / dept /
--   category / store / state). Materializing this collapses the 59M-row daily
--   scan into a small weekly fact, so downstream KPI views and downstream
--   Python loops NEVER re-scan fact_daily_sales (see docs/kpi_definitions.md).
--
-- NOTE: price rows exist only for sold (product,store,week) combos. Where a
--   week has units but no price row, sell_price/revenue are NULL (unpriced);
--   units still count, revenue does not. Documented in kpi_definitions.md.
-- ============================================================

DROP MATERIALIZED VIEW IF EXISTS mv_weekly_sales;

CREATE MATERIALIZED VIEW mv_weekly_sales AS
SELECT
    fds.product_surr_id,
    fds.store_surr_id,
    d.wm_yr_wk,
    min(d.week_id)                         AS week_id,
    sum(fds.units_sold)                    AS units,
    max(fwp.sell_price)                    AS sell_price,   -- constant within the week
    sum(fds.units_sold) * max(fwp.sell_price) AS revenue     -- units * weekly price
FROM fact_daily_sales fds
JOIN dim_date d               ON d.date_id = fds.date_id
LEFT JOIN fact_weekly_price fwp
       ON fwp.product_surr_id = fds.product_surr_id
      AND fwp.store_surr_id   = fds.store_surr_id
      AND fwp.wm_yr_wk        = d.wm_yr_wk
GROUP BY fds.product_surr_id, fds.store_surr_id, d.wm_yr_wk;

-- The duplicate-key guard: no (product, store, week) can appear twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_weekly_sales
    ON mv_weekly_sales(product_surr_id, store_surr_id, wm_yr_wk);

COMMENT ON MATERIALIZED VIEW mv_weekly_sales IS
    'Weekly product/store revenue anchor. revenue = units * sell_price at week grain. Phase 3B.';
