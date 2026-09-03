-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - VALIDATION / INTEGRITY CHECKS
-- Used by the ETL validation step AND as rerunnable SQL.
-- ============================================================

-- 1. Orphan check: every fact_daily_sales row resolves to valid dims.
SELECT 'orphan_sales_fk' AS check_name,
       COUNT(*) AS bad_rows
FROM fact_daily_sales f
LEFT JOIN dim_product p ON p.product_surr_id = f.product_surr_id
LEFT JOIN dim_store s   ON s.store_surr_id   = f.store_surr_id
LEFT JOIN dim_date d    ON d.date_id         = f.date_id
WHERE p.product_surr_id IS NULL OR s.store_surr_id IS NULL OR d.date_id IS NULL;

-- 2. Distinct products / stores / dates in fact_daily_sales
SELECT
    (SELECT COUNT(DISTINCT product_surr_id) FROM fact_daily_sales) AS n_products,
    (SELECT COUNT(DISTINCT store_surr_id)   FROM fact_daily_sales) AS n_stores,
    (SELECT COUNT(DISTINCT date_id)         FROM fact_daily_sales) AS n_days;

-- 3. Total observed demand
SELECT SUM(units_sold) AS total_demand,
       COUNT(*)        AS n_rows
FROM fact_daily_sales
WHERE demand_source = 'observed';

-- 4. Row count parity: staging long-form vs fact (dup-safe)
SELECT
    (SELECT COUNT(*) FROM stg_sales_daily) AS stg_rows,
    (SELECT COUNT(*) FROM fact_daily_sales) AS fact_rows;

-- 5. Dimension cardinality summary
SELECT 'dim_category' AS dim,    COUNT(*) FROM dim_category
UNION ALL SELECT 'dim_department', COUNT(*) FROM dim_department
UNION ALL SELECT 'dim_product',    COUNT(*) FROM dim_product
UNION ALL SELECT 'dim_store',      COUNT(*) FROM dim_store
UNION ALL SELECT 'dim_date',       COUNT(*) FROM dim_date;

-- 6. Price sanity (Phase 1 flagged max price 107.32 as a WARN)
SELECT MIN(sell_price), MAX(sell_price), COUNT(*) AS n_prices
FROM fact_weekly_price;

-- 7. Dup check on natural (composite) keys in facts
SELECT COUNT(*) AS dup_sales_keys FROM (
    SELECT product_surr_id, store_surr_id, date_id
    FROM fact_daily_sales GROUP BY 1,2,3 HAVING COUNT(*) > 1
) x;
