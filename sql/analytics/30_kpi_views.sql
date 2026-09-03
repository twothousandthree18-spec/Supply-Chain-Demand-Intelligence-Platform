-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 3B - SQL Analytical Layer
-- 30_kpi_views.sql : canonical KPI views
--
-- All KPI views read from the small materialized weekly anchor
-- (mv_weekly_sales) + conformed dimensions. They NEVER re-scan the
-- 59M-row fact_daily_sales (that was collapsed once in 10_mv_weekly_sales.sql).
-- Definitions are canonical: docs/kpi_definitions.md.
-- ============================================================

-- ---------------------------------------------------------------------------
-- Base weekly view (product x store x week joined to dimensions)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_weekly AS
SELECT
    m.product_surr_id,
    m.store_surr_id,
    m.wm_yr_wk,
    m.week_id,
    m.units,
    m.sell_price,
    m.revenue,
    p.product_id,
    p.category_surr_id,
    p.dept_surr_id,
    st.store_id,
    st.state_id,
    st.region_id,
    dd.year,
    dd.quarter,
    dd.month,
    dd.month_name
FROM mv_weekly_sales m
JOIN dim_product p  ON p.product_surr_id  = m.product_surr_id
JOIN dim_store st   ON st.store_surr_id   = m.store_surr_id
JOIN (
    SELECT wm_yr_wk,
           min(week_id)   AS week_id,
           min(year)      AS year,
           min(quarter)   AS quarter,
           min(month)     AS month,
           min(month_name) AS month_name
    FROM dim_date
    GROUP BY wm_yr_wk
) dd ON dd.wm_yr_wk = m.wm_yr_wk;

-- ---------------------------------------------------------------------------
-- Units (fully additive at every grain)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_units AS
SELECT
    date_id,
    product_surr_id,
    store_surr_id,
    units_sold
FROM fact_daily_sales
WHERE demand_source = 'observed';

-- ---------------------------------------------------------------------------
-- Revenue : sum(units * weekly sell_price) at any grain, from the anchor
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_revenue AS
SELECT
    wm_yr_wk,
    sum(units) AS units,
    sum(revenue) AS revenue,
    count(*) FILTER (WHERE revenue IS NOT NULL) AS priced_weeks,
    count(*) FILTER (WHERE revenue IS NULL)     AS unpriced_weeks,
    count(*) FILTER (WHERE revenue IS NULL AND units > 0) AS unpriced_units_weeks
FROM mv_weekly_sales
GROUP BY wm_yr_wk;

-- ---------------------------------------------------------------------------
-- Price (weekly grain; aggregated weighted price at higher grains)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_price_weekly AS
SELECT
    wm_yr_wk,
    avg(sell_price)                       AS avg_sell_price,
    (sum(revenue) / NULLIF(sum(units), 0)) AS weighted_price
FROM mv_weekly_sales
GROUP BY wm_yr_wk;

-- ---------------------------------------------------------------------------
-- GROWTH : WoW / QoQ / YoY on units & revenue (contiguous periods from dim_date)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_growth_wow AS
SELECT
    d.wm_yr_wk,
    min(d.week_id) AS week_id,
    SUM(m.units)   AS units,
    SUM(m.revenue) AS revenue,
    ROUND((SUM(m.units)   / NULLIF(LAG(SUM(m.units))   OVER (ORDER BY min(d.week_id)), 0) - 1) * 100, 2) AS wow_units_pct,
    ROUND((SUM(m.revenue) / NULLIF(LAG(SUM(m.revenue)) OVER (ORDER BY min(d.week_id)), 0) - 1) * 100, 2) AS wow_revenue_pct
FROM dim_date d
LEFT JOIN mv_weekly_sales m ON m.wm_yr_wk = d.wm_yr_wk
GROUP BY d.wm_yr_wk;

CREATE OR REPLACE VIEW v_growth_qoq AS
WITH q AS (
    SELECT dd.year, dd.quarter,
           SUM(m.units) AS units, SUM(m.revenue) AS revenue
    FROM mv_weekly_sales m
    JOIN (SELECT DISTINCT wm_yr_wk, year, quarter FROM dim_date) dd USING (wm_yr_wk)
    GROUP BY dd.year, dd.quarter
)
SELECT
    year, quarter,
    units, revenue,
    ROUND((units   / NULLIF(LAG(units)   OVER (ORDER BY year, quarter), 0) - 1) * 100, 2) AS qoq_units_pct,
    ROUND((revenue / NULLIF(LAG(revenue) OVER (ORDER BY year, quarter), 0) - 1) * 100, 2) AS qoq_revenue_pct
FROM q;

CREATE OR REPLACE VIEW v_growth_yoy AS
WITH y AS (
    SELECT dd.year,
           SUM(m.units) AS units, SUM(m.revenue) AS revenue
    FROM mv_weekly_sales m
    JOIN (SELECT DISTINCT wm_yr_wk, year FROM dim_date) dd USING (wm_yr_wk)
    GROUP BY dd.year
)
SELECT
    year, units, revenue,
    ROUND((units   / NULLIF(LAG(units)   OVER (ORDER BY year), 0) - 1) * 100, 2) AS yoy_units_pct,
    ROUND((revenue / NULLIF(LAG(revenue) OVER (ORDER BY year), 0) - 1) * 100, 2) AS yoy_revenue_pct
FROM y;

-- ---------------------------------------------------------------------------
-- CONTRIBUTION (Pareto) : product / department / category / store / state
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_product_contribution AS
WITH base AS (
    SELECT
        product_surr_id, product_id,
        SUM(units)   AS units,
        SUM(revenue) AS revenue
    FROM v_weekly
    GROUP BY product_surr_id, product_id
),
tot AS (
    SELECT sum(units) AS tot_units,
           sum(revenue) AS tot_revenue FROM base
)
SELECT
    b.product_surr_id,
    b.product_id,
    b.units,
    b.revenue,
    ROUND((b.revenue / NULLIF(t.tot_revenue, 0)) * 100, 4) AS revenue_share_pct,
    ROUND(SUM((b.revenue / NULLIF(t.tot_revenue, 0)) * 100)
          OVER (ORDER BY b.revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 4)
        AS cumulative_share_pct,
    ROW_NUMBER() OVER (ORDER BY b.revenue DESC) AS rank
FROM base b CROSS JOIN tot t;

CREATE OR REPLACE VIEW v_department_contribution AS
WITH base AS (
    SELECT dept_surr_id, category_surr_id,
           SUM(units) AS units, SUM(revenue) AS revenue
    FROM v_weekly
    GROUP BY dept_surr_id, category_surr_id
),
tot AS (SELECT sum(units) tot_units, sum(revenue) tot_revenue FROM base)
SELECT
    b.dept_surr_id, b.category_surr_id, b.units, b.revenue,
    ROUND((b.revenue / NULLIF(t.tot_revenue, 0)) * 100, 4) AS revenue_share_pct
FROM base b CROSS JOIN tot t;

CREATE OR REPLACE VIEW v_category_contribution AS
WITH base AS (
    SELECT category_surr_id,
           SUM(units) AS units, SUM(revenue) AS revenue
    FROM v_weekly
    GROUP BY category_surr_id
),
tot AS (SELECT sum(units) tot_units, sum(revenue) tot_revenue FROM base)
SELECT
    b.category_surr_id, b.units, b.revenue,
    ROUND((b.revenue / NULLIF(t.tot_revenue, 0)) * 100, 4) AS revenue_share_pct
FROM base b CROSS JOIN tot t;

CREATE OR REPLACE VIEW v_store_contribution AS
WITH base AS (
    SELECT store_surr_id, store_id, state_id, region_id,
           SUM(units) AS units, SUM(revenue) AS revenue
    FROM v_weekly
    GROUP BY store_surr_id, store_id, state_id, region_id
),
tot AS (SELECT sum(units) tot_units, sum(revenue) tot_revenue FROM base)
SELECT
    b.store_surr_id, b.store_id, b.state_id, b.region_id, b.units, b.revenue,
    ROUND((b.revenue / NULLIF(t.tot_revenue, 0)) * 100, 4) AS revenue_share_pct
FROM base b CROSS JOIN tot t;

CREATE OR REPLACE VIEW v_state_contribution AS
WITH base AS (
    SELECT state_id,
           SUM(units) AS units, SUM(revenue) AS revenue
    FROM v_weekly
    GROUP BY state_id
),
tot AS (SELECT sum(units) tot_units, sum(revenue) tot_revenue FROM base)
SELECT
    b.state_id, b.units, b.revenue,
    ROUND((b.revenue / NULLIF(t.tot_revenue, 0)) * 100, 4) AS revenue_share_pct
FROM base b CROSS JOIN tot t;

-- ---------------------------------------------------------------------------
-- ROLLUPS : daily / weekly / monthly ; product->dept->category ; store->state
-- ---------------------------------------------------------------------------
-- Daily rollup (base; reads the observed fact for additive reconciliation).
CREATE OR REPLACE VIEW v_rollup_daily AS
SELECT
    fds.date_id,
    d.calendar_date,
    d.wm_yr_wk,
    fds.product_surr_id,
    fds.store_surr_id,
    fds.units_sold
FROM fact_daily_sales fds
JOIN dim_date d ON d.date_id = fds.date_id
WHERE fds.demand_source = 'observed';

-- Weekly rollup (units always; revenue from priced weeks) - from anchor.
CREATE OR REPLACE VIEW v_rollup_weekly AS
SELECT wm_yr_wk, SUM(units) AS units, SUM(revenue) AS revenue
FROM mv_weekly_sales
GROUP BY wm_yr_wk;

-- Monthly rollup (week attributed to its first calendar month).
CREATE OR REPLACE VIEW v_rollup_monthly AS
SELECT year, month, SUM(units) AS units, SUM(revenue) AS revenue
FROM v_weekly
GROUP BY year, month;

-- product -> department -> category chain (per product with its dept/category).
CREATE OR REPLACE VIEW v_rollup_product_hierarchy AS
SELECT
    p.product_surr_id,
    p.product_id,
    p.dept_surr_id,
    p.category_surr_id,
    SUM(m.units) AS units,
    SUM(m.revenue) AS revenue
FROM dim_product p
LEFT JOIN mv_weekly_sales m ON m.product_surr_id = p.product_surr_id
GROUP BY p.product_surr_id, p.product_id, p.dept_surr_id, p.category_surr_id;

-- store -> state rollup (per store with its state/region).
CREATE OR REPLACE VIEW v_rollup_store_hierarchy AS
SELECT
    st.store_surr_id,
    st.store_id,
    st.state_id,
    st.region_id,
    SUM(m.units) AS units,
    SUM(m.revenue) AS revenue
FROM dim_store st
LEFT JOIN mv_weekly_sales m ON m.store_surr_id = st.store_surr_id
GROUP BY st.store_surr_id, st.store_id, st.state_id, st.region_id;
