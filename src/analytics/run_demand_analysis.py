"""
Supply Chain & Demand Intelligence Platform
Phase 3C - Demand analysis driver (bounded, resumable).

Computes and persists product-store demand-analysis metrics by reading the
Phase 3B materialized layer (mv_weekly_sales, fact_product_store_demand) plus a
single bounded day-of-week aggregation. It NEVER scans fact_daily_sales more
than once, and it does not re-scan the 59M fact for trend/volatility/growth
(those come from the already-materialized weekly anchor).

Outputs (all data_provenance = 'derived'):
  * fact_demand_analysis          - one row per (product, store, window)
  * fact_demand_seasonality       - monthly calendar seasonality (meaningful only)
  * fact_demand_seasonality_dow   - aggregate day-of-week (weekly) factors
  * demand_analysis_rules         - documented/reproducible thresholds

Resumable/idempotent: rows for the chosen analysis_window are deleted then
re-inserted, so a re-run overwrites cleanly without duplicating. Run status is
logged to etl_run_log (pipeline='demand_analysis'). An interrupted run is marked
failed on the next invocation (mirrors build_warehouse.py).

Formulas & definitions: docs/demand_analysis.md, config.py, metrics.py
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl.db_utils import connect
from src.analytics import config, metrics

ANALYSIS_WINDOW = "observed_full"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def fetch(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def fetch_one(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()


def to_native(v):
    """Coerce the value to a native Python type for psycopg2 binding.

    DataFrame rows expose numpy scalars (numpy.int64 etc.) which psycopg2 cannot
    always adapt directly; convert them to native int/float/bool (NaN -> None).
    """
    if v is None or isinstance(v, (str, bytes)):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        f = float(v)
        return None if np.isnan(f) else f
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


# --------------------------------------------------------------------------- #
# Pulls (aggregates computed in SQL so Python never sees the raw 59M fact)
# --------------------------------------------------------------------------- #
def pull_volume_quantiles(conn):
    row = fetch_one(
        conn,
        "SELECT percentile_cont(1.0/3.0) WITHIN GROUP (ORDER BY total_units::float8), "
        "       percentile_cont(2.0/3.0) WITHIN GROUP (ORDER BY total_units::float8) "
        "FROM fact_product_store_demand",
    )
    low_q, high_q = float(row[0]), float(row[1])
    return low_q, high_q


def pull_base_stats(conn):
    """Aggregate (30,490-row) stats already materialized by Phase 3B."""
    return fetch(conn, """
        SELECT product_surr_id, store_surr_id,
               series_start, series_end,
               total_units, mean_daily_units, std_daily_units, cv,
               zero_demand_days, trend_slope
        FROM fact_product_store_demand
        WHERE analysis_window = 'observed_full'
    """)


def pull_weekly_growth(conn):
    """Single aggregate pass over mv_weekly_sales: per-series weekly growth."""
    return fetch(conn, """
        WITH w AS (
            SELECT product_surr_id, store_surr_id, week_id, units,
                   ROW_NUMBER() OVER (
                       PARTITION BY product_surr_id, store_surr_id
                       ORDER BY week_id DESC) AS rn_desc
            FROM mv_weekly_sales
        )
        SELECT product_surr_id, store_surr_id,
               AVG(units) AS avg_week_units,
               AVG(units) FILTER (WHERE rn_desc BETWEEN 1 AND 4) AS recent_4wk_mean,
               AVG(units) FILTER (WHERE rn_desc BETWEEN 5 AND 8) AS prior_4wk_mean
        FROM w
        GROUP BY product_surr_id, store_surr_id
    """)


def pull_monthly_means(conn):
    """Single pass over mv_weekly_sales joined to dims: per-series monthly means."""
    return fetch(conn, """
        SELECT m.product_surr_id, m.store_surr_id, d.month,
               AVG(m.units) AS mean_weekly,
               COUNT(*) FILTER (WHERE m.units > 0) AS obs_weeks
        FROM mv_weekly_sales m
        JOIN (SELECT DISTINCT wm_yr_wk, month FROM dim_date) d ON d.wm_yr_wk = m.wm_yr_wk
        GROUP BY m.product_surr_id, m.store_surr_id, d.month
    """)


def pull_dow_fine(conn):
    """ONE scan over fact_daily_sales: day-of-week x store x category x dept x state."""
    return fetch(conn, """
        SELECT fds.store_surr_id, st.store_id, st.state_id,
               p.category_surr_id, p.dept_surr_id,
               d.weekday_num, d.weekday_name,
               SUM(fds.units_sold) AS units, COUNT(*) AS days
        FROM fact_daily_sales fds
        JOIN dim_date d     ON d.date_id = fds.date_id
        JOIN dim_product p  ON p.product_surr_id = fds.product_surr_id
        JOIN dim_store st   ON st.store_surr_id = fds.store_surr_id
        WHERE fds.demand_source = 'observed' AND d.is_observed
        GROUP BY fds.store_surr_id, st.store_id, st.state_id,
                 p.category_surr_id, p.dept_surr_id, d.weekday_num, d.weekday_name
    """)


def pull_dim_labels(conn):
    """Small mapping tables for human labels on DOW factor rows."""
    categories = fetch(conn,
        "SELECT category_surr_id, category_id FROM dim_category")
    depts = fetch(conn, "SELECT dept_surr_id, dept_id FROM dim_department")
    stores = fetch(conn, "SELECT store_surr_id, store_id FROM dim_store")
    return categories, depts, stores


# --------------------------------------------------------------------------- #
# Computations (vectorized over the 30,490-series frame)
# --------------------------------------------------------------------------- #
def build_analysis_frame(base, weekly, monthly, low_q, high_q):
    df = base.merge(weekly, on=["product_surr_id", "store_surr_id"], how="left")
    for col in ["total_units", "mean_daily_units", "std_daily_units", "cv",
                "trend_slope", "avg_week_units", "recent_4wk_mean", "prior_4wk_mean",
                "series_start", "series_end", "zero_demand_days"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["span_days"] = df["series_end"] - df["series_start"] + 1
    df["zero_demand_ratio"] = df["zero_demand_days"] / df["span_days"].replace(0, np.nan)

    rows = []
    monthly_map = {}
    for (pid, sid), g in monthly.groupby(["product_surr_id", "store_surr_id"]):
        d = dict(zip(g["month"].astype(int), g["mean_weekly"].astype(float)))
        monthly_map[(pid, sid)] = d

    for _, r in df.iterrows():
        pid, sid = int(r["product_surr_id"]), int(r["store_surr_id"])
        span = int(r["span_days"]) if not pd.isna(r["span_days"]) else 0

        recent = float(r["recent_4wk_mean"]) if not pd.isna(r["recent_4wk_mean"]) else None
        prior = float(r["prior_4wk_mean"]) if not pd.isna(r["prior_4wk_mean"]) else None
        growth_rate, defined = None, False
        denom_zero = False
        if recent is not None and prior is not None:
            growth_rate, defined = metrics.compute_growth(recent, prior)
            denom_zero = not defined

        mean_daily = float(r["mean_daily_units"]) if not pd.isna(r["mean_daily_units"]) else 0.0
        slope = float(r["trend_slope"]) if not pd.isna(r["trend_slope"]) else None
        effect = metrics.trend_effect_pct(slope, span, mean_daily) if slope is not None else None
        direction = metrics.trend_direction(slope, span, mean_daily)

        cv = float(r["cv"]) if not pd.isna(r["cv"]) else None
        total = float(r["total_units"]) if not pd.isna(r["total_units"]) else 0.0
        zero_ratio = float(r["zero_demand_ratio"]) if not pd.isna(r["zero_demand_ratio"]) else None

        seg = metrics.compute_seasonality(monthly_map.get((pid, sid), {}))
        n_active_months = seg["n_active_months"] if seg["meaningful"] else None

        volume = metrics.segment_volume(total, low_q, high_q)
        volatility = metrics.segment_volatility(cv)
        demand = metrics.classify_demand(zero_ratio)
        cell, index = metrics.classify_risk(volume, volatility)
        category = metrics.risk_category_from_index(index)

        rows.append({
            "product_surr_id": pid, "store_surr_id": sid,
            "series_start": int(r["series_start"]) if not pd.isna(r["series_start"]) else None,
            "series_end": int(r["series_end"]) if not pd.isna(r["series_end"]) else None,
            "total_units": total, "mean_daily_units": mean_daily,
            "std_daily_units": (float(r["std_daily_units"]) if not pd.isna(r["std_daily_units"]) else None),
            "cv": cv, "zero_demand_days": (int(r["zero_demand_days"]) if not pd.isna(r["zero_demand_days"]) else None),
            "zero_demand_ratio": zero_ratio,
            "avg_week_units": (float(r["avg_week_units"]) if not pd.isna(r["avg_week_units"]) else None),
            "recent_4wk_mean": recent, "prior_4wk_mean": prior,
            "demand_growth_rate": growth_rate,
            "growth_is_defined": bool(defined), "growth_denominator_zero": bool(denom_zero),
            "trend_slope": slope, "trend_effect_pct": effect, "trend_direction": direction,
            "seasonality_strength": seg["strength"],
            "has_meaningful_seasonality": bool(seg["meaningful"]),
            "peak_month": seg["peak_month"], "trough_month": seg["trough_month"],
            "n_active_months": n_active_months,
            "segment_volume": volume, "segment_volatility": volatility,
            "segment_demand": demand, "risk_cell": cell, "risk_category": category,
        })
    return pd.DataFrame(rows)


def build_dow_rows(fine, categories, depts, stores):
    """Collapse the fine day-of-week aggregation to per-scope DOW factors."""
    cat_by = {int(r["category_surr_id"]): r["category_id"] for _, r in categories.iterrows()}
    dep_by = {int(r["dept_surr_id"]): r["dept_id"] for _, r in depts.iterrows()}
    st_by = {int(r["store_surr_id"]): r["store_id"] for _, r in stores.iterrows()}
    fine["category_id"] = fine["category_surr_id"].map(cat_by)
    fine["dept_id"] = fine["dept_surr_id"].map(dep_by)
    fine["store_id"] = fine["store_surr_id"].map(st_by)

    rows = []
    dl = []
    for dt in ["units", "days"]:
        fine["f_" + dt] = pd.to_numeric(fine[dt], errors="coerce")
        dl.append("f_" + dt)

    # scope 'all'
    tot_units = fine["f_units"].sum()
    tot_days = fine["f_days"].sum()
    g = fine.groupby(["weekday_num", "weekday_name"])[["f_units", "f_days"]].sum().reset_index()
    for _, r in g.iterrows():
        day_mean = float(r["f_units"]) / float(r["f_days"])
        overall_mean = tot_units / tot_days
        idx = day_mean / overall_mean if overall_mean else None
        rows.append(("all", None, "all", int(r["weekday_num"]), r["weekday_name"], idx,
                     int(r["f_days"])))

    for label, key_col, val_col in [
        ("store", "store_id", "store_id"),
        ("state", "state_id", "state_id"),
        ("category", "category_id", "category_id"),
        ("dept", "dept_id", "dept_id"),
    ]:
        grp = fine.groupby([key_col, "weekday_num", "weekday_name"])[
            ["f_units", "f_days"]].sum().reset_index()
        for (key, wd, wdn), sg in grp.groupby([key_col, "weekday_num", "weekday_name"]):
            scope_units = grp[grp[key_col] == key]["f_units"].sum()
            scope_days = grp[grp[key_col] == key]["f_days"].sum()
            if scope_days == 0 or scope_units == 0:
                continue
            day_mean = float(sg["f_units"].sum()) / float(sg["f_days"].sum())
            scope_mean = scope_units / scope_days
            idx = day_mean / scope_mean if scope_mean else None
            rows.append((label, key, key, int(wd), wdn, idx, int(sg["f_days"].sum())))

    return pd.DataFrame(rows, columns=[
        "scope_type", "scope_key", "scope_value", "weekday_num", "weekday_name",
        "dow_index", "obs_days"])


# --------------------------------------------------------------------------- #
# Persistence (idempotent)
# --------------------------------------------------------------------------- #
def upsert_rules(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM demand_analysis_rules")
        for key, (value, desc) in config.RULES.items():
            cur.execute(
                "INSERT INTO demand_analysis_rules (rule_key, rule_value, description) "
                "VALUES (%s, %s, %s)", (key, value, desc))
    conn.commit()


def persist_analysis(conn, run_id, df):
    cols = ["product_surr_id", "store_surr_id", "series_start", "series_end",
            "total_units", "mean_daily_units", "std_daily_units", "cv",
            "zero_demand_days", "zero_demand_ratio", "avg_week_units",
            "recent_4wk_mean", "prior_4wk_mean", "demand_growth_rate",
            "growth_is_defined", "growth_denominator_zero", "trend_slope",
            "trend_effect_pct", "trend_direction", "seasonality_strength",
            "has_meaningful_seasonality", "peak_month", "trough_month",
            "n_active_months", "segment_volume", "segment_volatility",
            "segment_demand", "risk_cell", "risk_category"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fact_demand_analysis WHERE analysis_window = %s",
                    (ANALYSIS_WINDOW,))
        for _, r in df.iterrows():
            cur.execute(
                "INSERT INTO fact_demand_analysis (product_surr_id, store_surr_id, "
                "analysis_window, series_start, series_end, total_units, mean_daily_units, "
                "std_daily_units, cv, zero_demand_days, zero_demand_ratio, avg_week_units, "
                "recent_4wk_mean, prior_4wk_mean, demand_growth_rate, growth_is_defined, "
                "growth_denominator_zero, trend_slope, trend_effect_pct, trend_direction, "
                "seasonality_strength, has_meaningful_seasonality, peak_month, trough_month, "
                "n_active_months, segment_volume, segment_volatility, segment_demand, "
                "risk_cell, risk_category, data_provenance, etl_run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'derived',%s)",
                (to_native(r["product_surr_id"]), to_native(r["store_surr_id"]), ANALYSIS_WINDOW,
                 to_native(r["series_start"]), to_native(r["series_end"]), to_native(r["total_units"]),
                 to_native(r["mean_daily_units"]),
                 to_native(r["std_daily_units"]), to_native(r["cv"]), to_native(r["zero_demand_days"]),
                 to_native(r["zero_demand_ratio"]),
                 to_native(r["avg_week_units"]), to_native(r["recent_4wk_mean"]),
                 to_native(r["prior_4wk_mean"]),
                 to_native(r["demand_growth_rate"]), to_native(r["growth_is_defined"]),
                 to_native(r["growth_denominator_zero"]),
                 to_native(r["trend_slope"]), to_native(r["trend_effect_pct"]),
                 to_native(r["trend_direction"]),
                 to_native(r["seasonality_strength"]), to_native(r["has_meaningful_seasonality"]),
                 to_native(r["peak_month"]),
                 to_native(r["trough_month"]), to_native(r["n_active_months"]),
                 to_native(r["segment_volume"]),
                 to_native(r["segment_volatility"]), to_native(r["segment_demand"]),
                 to_native(r["risk_cell"]),
                 to_native(r["risk_category"]), run_id))
    conn.commit()


def persist_seasonality(conn, run_id, base, monthly):
    rows = []
    monthly_map = {}
    for (pid, sid), g in monthly.groupby(["product_surr_id", "store_surr_id"]):
        d = dict(zip(g["month"].astype(int), g["mean_weekly"].astype(float)))
        monthly_map[(pid, sid)] = d
    meaningful = base.set_index(["product_surr_id", "store_surr_id"])[
        "has_meaningful_seasonality"].astype(bool)
    for (pid, sid), means in monthly_map.items():
        if pid not in meaningful.index or not meaningful.loc[pid, sid]:
            continue
        seg = metrics.compute_seasonality(means)
        obs = monthly[(monthly["product_surr_id"] == pid) &
                      (monthly["store_surr_id"] == sid)]
        obs_map = dict(zip(obs["month"].astype(int), obs["obs_weeks"].astype(int)))
        for month, idx in seg["indices"].items():
            rows.append((pid, sid, month, idx, obs_map.get(month, 0)))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fact_demand_seasonality WHERE analysis_window = %s",
                    (ANALYSIS_WINDOW,))
        for pid, sid, month, idx, obs in rows:
            cur.execute(
                "INSERT INTO fact_demand_seasonality (product_surr_id, store_surr_id, "
                "analysis_window, month, seasonality_index, obs_weeks, is_meaningful, "
                "data_provenance, etl_run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,TRUE,'derived',%s)",
                (to_native(pid), to_native(sid), ANALYSIS_WINDOW, to_native(month),
                 to_native(idx), to_native(obs), run_id))
    conn.commit()
    return len(rows)


def persist_dow(conn, run_id, df):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fact_demand_seasonality_dow")
        for _, r in df.iterrows():
            cur.execute(
                "INSERT INTO fact_demand_seasonality_dow (scope_type, scope_key, scope_value, "
                "weekday_num, weekday_name, dow_index, obs_days, data_provenance, etl_run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'derived',%s)",
                (to_native(r["scope_type"]), to_native(r["scope_key"]),
                 to_native(r["scope_value"]), to_native(r["weekday_num"]),
                 to_native(r["weekday_name"]), to_native(r["dow_index"]),
                 to_native(r["obs_days"]), run_id))
    conn.commit()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Phase 3C demand analysis")
    parser.add_argument("--window", default=ANALYSIS_WINDOW)
    args = parser.parse_args()

    conn = connect()
    conn.set_client_encoding("UTF8")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_run_log SET status='failed', error_message='abandoned (no live process)' "
            "WHERE status='running' AND pipeline='demand_analysis'")
    with conn.cursor() as cur:
        cur.execute("SELECT start_etl_run('demand_analysis')")
        run_id = cur.fetchone()[0]
    conn.commit()
    print(f"demand_analysis run_id={run_id} window={args.window}")
    t0 = time.time()

    try:
        print("  ... upserting documented thresholds (demand_analysis_rules)")
        upsert_rules(conn)

        print("  ... computing volume quantiles")
        low_q, high_q = pull_volume_quantiles(conn)
        print(f"    volume terciles: low={low_q:.1f} high={high_q:.1f}")

        print("  ... pulling per-series base stats (fact_product_store_demand)")
        base = pull_base_stats(conn)
        print(f"    {len(base):,} series")

        print("  ... computing weekly growth (single pass over mv_weekly_sales)")
        weekly = pull_weekly_growth(conn)
        print(f"    {len(weekly):,} series")

        print("  ... computing monthly seasonality means (single pass over mv_weekly_sales)")
        monthly = pull_monthly_means(conn)
        print(f"    {len(monthly):,} series-month rows")

        print("  ... day-of-week aggregation (single bounded scan of daily fact)")
        fine = pull_dow_fine(conn)
        print(f"    {len(fine)} fine groups")

        print("  ... computing analysis metrics")
        df = build_analysis_frame(base, weekly, monthly, low_q, high_q)

        print("  ... persisting fact_demand_analysis")
        persist_analysis(conn, run_id, df)
        print(f"    {len(df):,} rows")

        print("  ... persisting fact_demand_seasonality")
        n_seas = persist_seasonality(conn, run_id, df, monthly)
        print(f"    {n_seas:,} seasonality rows")

        print("  ... persisting day-of-week factors")
        categories, depts, stores = pull_dim_labels(conn)
        dow = build_dow_rows(fine, categories, depts, stores)
        persist_dow(conn, run_id, dow)
        print(f"    {len(dow)} dow rows")

        with conn.cursor() as cur:
            cur.execute("SELECT finish_etl_run(%s,'success',%s,%s)",
                        (run_id, len(df), len(df)))
        conn.commit()
        elapsed = time.time() - t0
        print(f"[ok] demand analysis complete in {elapsed:.1f}s")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT finish_etl_run(%s,'failed',0,0,%s)", (run_id, str(e)))
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
