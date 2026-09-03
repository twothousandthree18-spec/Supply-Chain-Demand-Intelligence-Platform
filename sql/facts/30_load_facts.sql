-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - FACT LOADING (staging -> fact tables)
-- Idempotent (rerunnable without duplicating rows).
-- ============================================================

-- ---------- fact_daily_sales ----------
-- grain = (product, store, day). Row-count safe: source is already one row
-- per product/store/day; joins use unique natural keys so no fan-out occurs.
INSERT INTO fact_daily_sales (product_surr_id, store_surr_id, date_id, units_sold, demand_source)
SELECT
    p.product_surr_id,
    st.store_surr_id,
    s.day_index AS date_id,
    s.units,
    'observed'
FROM stg_sales_daily s
JOIN dim_product p ON p.product_id = s.item_id
JOIN dim_store st  ON st.store_id  = s.store_id
ON CONFLICT (product_surr_id, store_surr_id, date_id) DO NOTHING;

-- ---------- fact_weekly_price ----------
-- grain = (product, store, week). Joins use unique keys; no row multiplication.
INSERT INTO fact_weekly_price (product_surr_id, store_surr_id, wm_yr_wk, week_id, sell_price)
SELECT
    p.product_surr_id,
    st.store_surr_id,
    sp.wm_yr_wk,
    w.week_id,
    sp.sell_price
FROM stg_sell_prices sp
JOIN dim_product p ON p.product_id = sp.item_id
JOIN dim_store st  ON st.store_id  = sp.store_id
JOIN (SELECT DISTINCT wm_yr_wk, week_id FROM dim_date) w ON w.wm_yr_wk = sp.wm_yr_wk
ON CONFLICT (product_surr_id, store_surr_id, wm_yr_wk) DO NOTHING;
