-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3B - SQL Analytical Layer
-- 20_demand_stats.sql : product-store demand statistics
--
-- Populates fact_product_store_demand (grain product x store x analysis_window)
-- with a SINGLE set-based aggregation over fact_daily_sales. This is the heavy
-- 59M-row precompute that Phase 3C (demand analysis) and Phase 3F
-- (safety-stock/reorder) reuse WITHOUT recomputing.
--
-- Idempotent/resumable: rows for the analysis_window are replaced (DELETE then
-- INSERT), so a re-run overwrites cleanly and never duplicates.
-- ============================================================

BEGIN;

DELETE FROM fact_product_store_demand;

INSERT INTO fact_product_store_demand (
    product_surr_id, store_surr_id, analysis_window,
    series_start, series_end,
    total_units, mean_daily_units, std_daily_units, cv,
    zero_demand_days, demand_growth_rate, trend_slope
)
SELECT
    a.product_surr_id,
    a.store_surr_id,
    'observed_full'                                   AS analysis_window,
    a.series_start,
    a.series_end,
    a.total_units,
    ROUND(a.total_units::numeric / NULLIF(a.series_end - a.series_start + 1, 0), 4)
        AS mean_daily_units,
    ROUND(a.std_daily_units, 4)                       AS std_daily_units,
    ROUND(
        a.std_daily_units / NULLIF(a.mean_daily_units, 0), 4
    )                                                 AS cv,
    a.zero_demand_days,
    ROUND(a.growth_rate, 6)                           AS demand_growth_rate,
    ROUND(a.trend_slope::numeric, 8)                  AS trend_slope
FROM (
    SELECT
        product_surr_id,
        store_surr_id,
        min(date_id)  AS series_start,
        max(date_id)  AS series_end,
        sum(units_sold) AS total_units,
        avg(units_sold) AS mean_daily_units,
        stddev(units_sold) AS std_daily_units,
        count(*) FILTER (WHERE units_sold = 0) AS zero_demand_days,
        -- recent 28-day mean / prior 28-day mean - 1
        (   (sum(units_sold) FILTER (WHERE date_id > maxd - 28))
          / NULLIF((sum(units_sold) FILTER (WHERE date_id BETWEEN maxd - 55 AND maxd - 28)), 0)
        ) - 1.0 AS growth_rate,
        regr_slope(units_sold, date_id) AS trend_slope
    FROM (
        SELECT product_surr_id, store_surr_id, date_id, units_sold,
               max(date_id) OVER (PARTITION BY product_surr_id, store_surr_id) AS maxd
        FROM fact_daily_sales
    ) t
    GROUP BY product_surr_id, store_surr_id
) a
ORDER BY product_surr_id, store_surr_id;

COMMIT;

COMMENT ON TABLE fact_product_store_demand IS
    'Derived demand statistics per product/store (analysis_window=observed_full). Populated in Phase 3B.';
