-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - DIMENSION LOADING (staging -> dimension tables)
-- Idempotent (rerunnable without duplicating rows).
-- ============================================================

-- ---------- dim_category ----------
INSERT INTO dim_category (category_id, category_name)
SELECT DISTINCT m.cat_id, m.cat_id
FROM stg_sales_meta m
ON CONFLICT (category_id) DO NOTHING;

-- ---------- dim_department ----------
INSERT INTO dim_department (dept_id, dept_name, category_id, category_surr_id)
SELECT DISTINCT m.dept_id, m.dept_id, m.cat_id, c.category_surr_id
FROM stg_sales_meta m
JOIN dim_category c ON c.category_id = m.cat_id
ON CONFLICT (dept_id) DO NOTHING;

-- ---------- dim_store (region from state) ----------
INSERT INTO dim_store (store_id, state_id, region_id, store_name)
SELECT DISTINCT
    m.store_id,
    m.state_id,
    CASE m.state_id
        WHEN 'CA' THEN 'West'
        WHEN 'TX' THEN 'Central'
        WHEN 'WI' THEN 'East'
        ELSE 'Unknown'
    END AS region_id,
    m.store_id AS store_name
FROM stg_sales_meta m
ON CONFLICT (store_id) DO NOTHING;

-- ---------- dim_product ----------
INSERT INTO dim_product (product_id, item_id, dept_id, dept_surr_id,
                         category_id, category_surr_id, product_label)
SELECT DISTINCT
    m.item_id AS product_id,
    m.item_id AS item_id,
    m.dept_id,
    d.dept_surr_id,
    m.cat_id,
    c.category_surr_id,
    m.item_id AS product_label
FROM stg_sales_meta m
JOIN dim_department d ON d.dept_id = m.dept_id
JOIN dim_category c   ON c.category_id = m.cat_id
ON CONFLICT (product_id) DO NOTHING;

-- ---------- dim_date ----------
-- date_id == M5 day index (strip 'd_' prefix). week_id = ordinal of distinct
-- wm_yr_wk (all days within one Walmart week share the same week_id).
WITH week_ordinal AS (
    SELECT wm_yr_wk,
           ROW_NUMBER() OVER (ORDER BY MIN(calendar_date)) AS week_id
    FROM (
        SELECT wm_yr_wk, date AS calendar_date
        FROM stg_calendar
    ) t
    GROUP BY wm_yr_wk
)
INSERT INTO dim_date (
    date_id, calendar_date, day_index, wm_yr_wk, week_id,
    weekday_num, weekday_name, is_weekend, month, month_name, quarter, year,
    is_event_day, event_name_1, event_type_1, event_name_2, event_type_2,
    snap_ca, snap_tx, snap_wi, is_observed
)
SELECT
    (regexp_replace(s.d, '^d_', ''))::int AS date_id,
    s.date AS calendar_date,
    (regexp_replace(s.d, '^d_', ''))::int AS day_index,
    s.wm_yr_wk,
    w.week_id,
    s.wday AS weekday_num,
    s.weekday AS weekday_name,
    (lower(s.weekday) IN ('saturday','sunday')) AS is_weekend,
    s.month,
    to_char(s.date, 'TMMonth') AS month_name,
    (EXTRACT(QUARTER FROM s.date))::int AS quarter,
    s.year,
    (s.event_name_1 IS NOT NULL) AS is_event_day,
    s.event_name_1, s.event_type_1, s.event_name_2, s.event_type_2,
    (s.snap_ca = 1) AS snap_ca,
    (s.snap_tx = 1) AS snap_tx,
    (s.snap_wi = 1) AS snap_wi,
    TRUE AS is_observed
FROM stg_calendar s
JOIN week_ordinal w ON w.wm_yr_wk = s.wm_yr_wk
ORDER BY date_id
ON CONFLICT (date_id) DO NOTHING;

-- ---------- dim_event (from calendar event fields) ----------
INSERT INTO dim_event (event_date, date_id, event_name, event_type, event_ordinal)
SELECT s.date, (regexp_replace(s.d, '^d_', ''))::int, s.event_name_1, s.event_type_1, 1
FROM stg_calendar s
WHERE s.event_name_1 IS NOT NULL
UNION ALL
SELECT s.date, (regexp_replace(s.d, '^d_', ''))::int, s.event_name_2, s.event_type_2, 2
FROM stg_calendar s
WHERE s.event_name_2 IS NOT NULL
ON CONFLICT (event_date, event_name, event_ordinal) DO NOTHING;
