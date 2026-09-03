"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Forecasting driver (bounded, resumable).

Produces and persists product/store/day demand forecasts and their honest
chronological-holdout evaluation:

  * data contract: observed-only daily demand, chronological, no NaN/Inf, no gaps
  * baselines (naive, seasonal-naive, moving & weighted moving average) on ALL
    30,490 product/store series (vectorized numpy over a single bounded pull)
  * statistical models (ETS/Holt-Winters, SARIMA) ONLY on a bounded pilot subset
    (top-N series by lifetime units) - never 30,490 uncontrolled fits
  * chronological single-origin holdout: train [1,1913], validate [1914,1941]
  * per-series model selection (a statistical model wins a series only if it
    beats the best baseline by the documented WMAE margin)
  * final forecast at origin 1941 for days [1942,1969] with ~95% intervals
  * outputs -> model_registry, fact_forecast, fact_forecast_evaluation,
    forecast_rules (all data_provenance='derived')

Bounded/resumable: single filtered scan of the observed fact; batched DB writes
with periodic commits; idempotent (DELETE + INSERT per run, children before the
FK parent); interrupted runs are marked failed on the next invocation.

Run with `--pilot-only` to print the bounded statistical pilot comparison and
exit without any DB writes (used to document whether advanced models are
worthwhile before the full run).

Definitions: docs/forecasting_architecture.md, config.py, metrics.py, models.py.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from src.etl.db_utils import connect
from src.forecasting import config, datacontract, metrics, models, selection

PIPELINE = "forecasting"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def fetch(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def to_native(v):
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


def _round(v, digits=6):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(f"{float(v):.{digits}f}")


def batch_executemany(conn, sql, rows, chunk=5000, commit_every=8):
    cur = conn.cursor()
    inserted = 0
    for i in range(0, len(rows), chunk):
        piece = rows[i:i + chunk]
        cur.executemany(sql, piece)
        inserted += len(piece)
        if inserted % (chunk * commit_every) == 0:
            conn.commit()
    conn.commit()
    cur.close()
    return inserted


def json_safe(obj):
    def conv(v):
        if isinstance(v, (float, np.floating)) and not np.isfinite(v):
            return None
        return v
    return {k: conv(v) for k, v in obj.items()}


def _git_ref():
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Data pulls (bounded)
# --------------------------------------------------------------------------- #
def pull_series_meta(conn):
    df = fetch(conn, """
        SELECT product_surr_id, store_surr_id, total_units
        FROM fact_product_store_demand
        WHERE analysis_window = 'observed_full'
        ORDER BY product_surr_id, store_surr_id
    """)
    df["total_units"] = pd.to_numeric(df["total_units"], errors="coerce").fillna(0).astype(float)
    return df


def pull_trailing_window(conn):
    """ONE filtered scan of the observed fact for days [1900,1941]; pivoted to a
    (n_series x 42) matrix indexed by date. Covers eval trailing, holdout actuals
    and final trailing for the baselines, without scanning the full 59M fact."""
    df = fetch(conn, """
        SELECT product_surr_id, store_surr_id, date_id, units_sold
        FROM fact_daily_sales
        WHERE demand_source='observed' AND date_id BETWEEN 1900 AND 1941
    """)
    df["units_sold"] = pd.to_numeric(df["units_sold"], errors="coerce")
    piv = df.pivot_table(index=["product_surr_id", "store_surr_id"],
                         columns="date_id", values="units_sold",
                         aggfunc="sum", fill_value=0)
    days = list(range(1900, 1942))
    piv = piv.reindex(columns=days, fill_value=0)
    keys = pd.DataFrame(piv.index.to_list(), columns=["product_surr_id", "store_surr_id"])
    mat = piv.to_numpy(dtype=np.float64)          # (n x 42), col 0 = day 1900
    return keys, mat


def col_slice(mat, day_start, day_end):
    c0 = day_start - 1900
    c1 = day_end - 1900 + 1
    return mat[:, c0:c1]


def pull_pilot_series(conn, top_n):
    df = fetch(conn, f"""
        SELECT product_surr_id, store_surr_id
        FROM fact_product_store_demand
        WHERE analysis_window='observed_full'
        ORDER BY total_units DESC
        LIMIT {int(top_n)}
    """)
    return list(zip(df["product_surr_id"].astype(int), df["store_surr_id"].astype(int)))


def pull_pilot_full(conn, pilot_series):
    """Full daily series [1,1941] for the bounded pilot subset."""
    if not pilot_series:
        return {}
    # build a safe integer IN list (ints come from the DB)
    pairs = ",".join(f"({int(a)},{int(b)})" for a, b in pilot_series)
    df = fetch(conn, f"""
        SELECT product_surr_id, store_surr_id, date_id, units_sold
        FROM fact_daily_sales
        WHERE demand_source='observed'
          AND (product_surr_id, store_surr_id) IN ({pairs})
          AND date_id BETWEEN 1 AND {config.OBSERVED_END}
        ORDER BY product_surr_id, store_surr_id, date_id
    """)
    out = {}
    for (pid, sid), g in df.groupby(["product_surr_id", "store_surr_id"]):
        g = g.set_index("date_id").sort_index()
        ts = g["units_sold"].to_numpy(dtype=np.float64)
        if ts.shape[0] == config.OBSERVED_END:
            out[(int(pid), int(sid))] = ts          # index 0 = day 1
    return out


# --------------------------------------------------------------------------- #
# Evaluation helpers
# --------------------------------------------------------------------------- #
def series_metrics_dict(fc, actual, weight):
    e = fc - actual
    wsum = float(actual.sum())
    if wsum <= 0:
        wsum = 1.0
    return {
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e ** 2))),
        "wmae": float(np.sum(actual * np.abs(e)) / wsum),
        "wrmse": float(np.sqrt(np.sum(actual * e ** 2) / wsum)),
        "abs_error": float(np.sum(np.abs(e))),
        "bias": float(np.mean(e)),
        "sigma": float(np.std(e, ddof=1)) if e.size > 1 else None,
        # between-series aggregation weight for aggregate_weighted_metrics
        "weight": float(weight) if weight is not None else wsum,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Phase 3D forecasting driver")
    parser.add_argument("--pilot-only", action="store_true",
                        help="print the bounded statistical pilot comparison and exit "
                             "(no DB writes)")
    args = parser.parse_args()

    conn = connect()
    conn.set_client_encoding("UTF8")

    if not args.pilot_only:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE etl_run_log SET status='failed', error_message='abandoned (no live process)' "
                "WHERE status='running' AND pipeline=%s", (PIPELINE,))
        with conn.cursor() as cur:
            cur.execute("SELECT start_etl_run(%s)", (PIPELINE,))
            run_id = cur.fetchone()[0]
        conn.commit()
    else:
        run_id = None

    print(f"[forecasting] run_id={run_id} pilot_only={args.pilot_only}")
    t0 = time.time()

    try:
        # --------------------------- pulls -------------------------------- #
        print("  ... pulling series metadata")
        meta = pull_series_meta(conn)
        totals = meta["total_units"].to_numpy(dtype=np.float64)
        n_series = totals.shape[0]
        print(f"    {n_series:,} series")

        print("  ... pulling bounded observed trailing window [1900,1941]")
        keys, mat = pull_trailing_window(conn)
        assert mat is not None, "no observed trailing data pulled"
        pid = keys["product_surr_id"].to_numpy().astype(int)
        sid = keys["store_surr_id"].to_numpy().astype(int)

        eval_trail = col_slice(mat, 1900, 1913)      # train tail (origin 1913)
        eval_actual = col_slice(mat, 1914, 1941)     # holdout actuals (28 days)
        final_trail = col_slice(mat, 1928, 1941)     # origin 1941 tail
        print(f"    eval_trail={eval_trail.shape} eval_actual={eval_actual.shape} "
              f"final_trail={final_trail.shape}")

        # data contract on the evaluation/trailing window
        for i in range(n_series):
            row = np.concatenate([eval_trail[i], eval_actual[i]])
            datacontract.validate_series(np.arange(1900, 1942), row, "observed")
        print("    data contract OK (chronological, no NaN/Inf/gaps, provenance observed)")

        # --------------------- baselines (all series) --------------------- #
        print("  ... evaluating baselines on all series (holdout [1914,1941])")
        baseline_eval = {}
        sigma_eval = {}
        per_model_metrics = {m: [] for m in models.BASELINES}
        for m in models.BASELINES:
            fc = models.BASELINES[m](eval_trail, config.VALIDATION_HORIZON)
            baseline_eval[m] = fc
            for i in range(n_series):
                per_model_metrics[m].append(series_metrics_dict(fc[i], eval_actual[i], totals[i]))
            resid = fc - eval_actual
            with np.errstate(invalid="ignore", divide="ignore"):
                st = np.sqrt(np.where(eval_actual.shape[1] > 1, np.var(resid, axis=1, ddof=1), np.nan))
                st[~np.isfinite(st)] = np.nan
            sigma_eval[m] = st
            agg = metrics.aggregate_weighted_metrics(per_model_metrics[m])
            print(f"    baseline {m:16s} WMAE={agg.get('wmae'):.4f} "
                  f"WRMSE={agg.get('wrmse'):.4f} bias={agg.get('bias'):+.4f}")

        # ----------------------- statistical pilot ------------------------ #
        print(f"  ... statistical pilot subset (top-{config.PILOT_TOP_N} series)")
        pilot_series = pull_pilot_series(conn, config.PILOT_TOP_N)
        pilot_full = pull_pilot_full(conn, pilot_series)
        key_to_row = {(int(pid[i]), int(sid[i])): i for i in range(n_series)}
        pilot_rows = [key_to_row[k] for k in pilot_series if k in key_to_row]
        print(f"    {len(pilot_rows)} of {len(pilot_series)} pilot series have full history")

        stat_eval = {m: {} for m in models.STATISTICAL}     # model -> {row: fc}
        per_stat_metrics = {m: [] for m in models.STATISTICAL}
        stat_ok = {m: 0 for m in models.STATISTICAL}
        stat_fail = {m: 0 for m in models.STATISTICAL}
        for r in pilot_rows:
            k = (int(pid[r]), int(sid[r]))
            full = pilot_full.get(k)
            if full is None:
                continue
            train = full[:config.VALIDATION_START - 1]        # days [1,1913]
            for m, fitter in models.STATISTICAL.items():
                res = fitter(train, config.VALIDATION_HORIZON)
                stat_eval[m][r] = res.point
                if res.ok:
                    stat_ok[m] += 1
                else:
                    stat_fail[m] += 1
                per_stat_metrics[m].append(series_metrics_dict(res.point, eval_actual[r], totals[r]))

        # pilot comparison on the SAME subset
        sub_agg = {m: metrics.aggregate_weighted_metrics(
            [per_model_metrics[m][r] for r in pilot_rows]) for m in models.BASELINES}
        best_base = min(sub_agg, key=lambda m: sub_agg[m].get("wmae", 1e18))
        best_base_wmae = sub_agg[best_base].get("wmae")
        print("  ---- PILOT COMPARISON (union of pilot series) ----")
        for m in models.STATISTICAL:
            a = metrics.aggregate_weighted_metrics(per_stat_metrics[m])
            wins = selection.statistical_wins(a.get("wmae"), best_base_wmae)
            print(f"    stats {m:18s} WMAE={a.get('wmae'):.4f} ok={stat_ok[m]} "
                  f"fail={stat_fail[m]} beats_best_baseline={wins}")
        print(f"    best baseline on pilot subset = {best_base} WMAE={best_base_wmae:.4f}")

        if args.pilot_only:
            print(f"[ok] pilot-only complete; no DB writes. elapsed={time.time()-t0:.1f}s")
            conn.close()
            return

        # --------------------- per-series selection ----------------------- #
        print("  ... selecting per-series model")
        pilot_set = set(pilot_rows)
        selected = []
        for i in range(n_series):
            wmae_by_baseline = {m: per_model_metrics[m][i].get("wmae", None)
                                for m in models.BASELINES}
            is_pilot = i in pilot_set
            if is_pilot:
                for m in models.STATISTICAL:
                    if i in stat_eval[m]:
                        fc = stat_eval[m][i]
                        wmae_by_baseline[m] = series_metrics_dict(
                            fc, eval_actual[i], totals[i]).get("wmae", None)
            sel = selection.select_for_series(wmae_by_baseline, statistical_subset=is_pilot)
            selected.append(sel)
        champ = selection.champion_model(selected)
        from collections import Counter
        sel_counts = Counter(selected)
        print(f"    per-series selected: {dict(sel_counts)} (champion baseline={champ})")

        # --------------------- persistence (FK-safe order) --------------- #
        # children first, then parent model_registry, then children again
        print("  ... clearing previous derived forecast rows")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fact_forecast")
            cur.execute("DELETE FROM fact_forecast_evaluation")
            cur.execute("DELETE FROM model_registry")
            cur.execute("DELETE FROM forecast_rules")
        conn.commit()

        print("  ... writing forecast_rules")
        with conn.cursor() as cur:
            for key, (value, desc) in config.RULES.items():
                cur.execute(
                    "INSERT INTO forecast_rules (rule_key, rule_value, description) "
                    "VALUES (%s,%s,%s)", (key, value, desc))
        conn.commit()

        print("  ... writing model_registry")
        model_id = _write_model_registry(conn, run_id, per_model_metrics, per_stat_metrics,
                                         champ, sel_counts, best_base, best_base_wmae,
                                         stat_ok, stat_fail)
        print(f"    {len(model_id)} models registered")

        print("  ... writing fact_forecast_evaluation (realized holdout)")
        n_eval = _write_evaluation(conn, run_id, model_id, per_model_metrics,
                                   stat_eval, pid, sid, eval_actual, totals)
        print(f"    {n_eval:,} evaluation rows")

        print("  ... computing final forecasts [1942,1969] + intervals (origin 1941)")
        n_fcast = _write_final_forecasts(conn, run_id, model_id, selected, pid, sid,
                                         final_trail, eval_actual, sigma_eval,
                                         stat_eval, pilot_rows, pilot_full, totals)
        print(f"    {n_fcast:,} forecast rows")

        with conn.cursor() as cur:
            cur.execute("SELECT finish_etl_run(%s,'success',%s,%s)", (run_id, n_series, n_series))
        conn.commit()
        print(f"[ok] forecasting complete in {time.time()-t0:.1f}s")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        if run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT finish_etl_run(%s,'failed',0,0,%s)", (run_id, str(e)))
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Persistence writers
# --------------------------------------------------------------------------- #
MODEL_ORDER = list(models.BASELINES) + list(models.STATISTICAL)


def _write_model_registry(conn, run_id, per_model_metrics, per_stat_metrics, champ,
                          sel_counts, best_base, best_base_wmae, stat_ok, stat_fail):
    model_id = {}
    with conn.cursor() as cur:
        for i, m in enumerate(MODEL_ORDER, start=1):
            if m in models.BASELINES:
                agg = metrics.aggregate_weighted_metrics(per_model_metrics[m])
                is_sel = m == champ
                rationale = (f"Champion baseline: most-frequent per-series WMAE winner "
                             f"({sel_counts.get(m, 0)}/{sum(sel_counts.values())} series)."
                             if is_sel else
                             f"Not selected as champion: beat on per-series WMAE "
                             f"(won {sel_counts.get(m, 0)} series).")
            else:
                agg = metrics.aggregate_weighted_metrics(per_stat_metrics[m])
                wins = selection.statistical_wins(agg.get("wmae"), best_base_wmae)
                is_sel = bool(wins)
                rationale = (f"Selected on pilot subset: beat best baseline ({best_base}, "
                             f"WMAE {best_base_wmae:.4f}) by >= "
                             f"{config.SELECTION_IMPROVEMENT:.0%} margin. ok={stat_ok[m]} "
                             f"fail={stat_fail[m]}." if wins else
                             f"Rejected: did NOT beat best baseline ({best_base}, "
                             f"WMAE {best_base_wmae:.4f}) by the documented margin. "
                             f"ok={stat_ok[m]} fail={stat_fail[m]}.")
            cur.execute(
                "INSERT INTO model_registry "
                "(model_name, model_family, params_json, training_window, validation_method, "
                "training_start, training_end, validation_start, validation_end, "
                "metrics_json, selection_rationale, is_selected, git_ref, data_provenance, etl_run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'derived',%s) RETURNING model_id",
                (m, "baseline" if m in models.BASELINES else "statistical",
                 _params(m), f"{config.VALIDATION_START}-{config.VALIDATION_END}",
                 "chronological_holdout",
                 config.OBSERVED_START, config.TRAIN_END,
                 config.VALIDATION_START, config.VALIDATION_END,
                 json.dumps(json_safe(agg)), rationale, is_sel, _git_ref(), run_id))
            model_id[m] = cur.fetchone()[0]
    conn.commit()
    return model_id


def _params(m):
    if m == "naive":
        return json.dumps({"method": "last observed value"})
    if m == "seasonal_naive":
        return json.dumps({"method": "last week's DOW pattern", "period": config.SEASONALITY})
    if m == "moving_average":
        return json.dumps({"method": "mean of last window days", "window": config.MA_WINDOW})
    if m == "weighted_ma":
        return json.dumps({"method": "linearly-weighted mean of last window days",
                           "window": config.MA_WINDOW})
    if m == "ets_holt_winters":
        return json.dumps({"method": "ETS Holt-Winters additive", "trend": "add",
                           "seasonal": "add", "seasonal_periods": config.SEASONALITY,
                           "fallback": "SES/naive"})
    if m == "sarima":
        return json.dumps({"method": "SARIMA", "order": [0, 1, 1],
                           "seasonal_order": [0, 1, 1, config.SEASONALITY],
                           "fallback": "seasonal-naive"})
    return json.dumps({})


def _write_evaluation(conn, run_id, model_id, per_model_metrics, stat_eval,
                      pid, sid, eval_actual, totals):
    rows = []
    for i in range(len(pid)):
        for m in models.BASELINES:
            d = per_model_metrics[m][i]
            rows.append((model_id[m], int(pid[i]), int(sid[i]),
                         config.VALIDATION_START, config.VALIDATION_END,
                         _round(d["mae"]), _round(d["rmse"]), _round(d["wmae"]),
                         _round(d["wrmse"]), _round(d["abs_error"]), _round(d["bias"]),
                         28, run_id))
    for m, by_row in stat_eval.items():
        for i, fc in by_row.items():
            if fc is None:
                continue
            d = series_metrics_dict(fc, eval_actual[i], totals[i])
            rows.append((model_id[m], int(pid[i]), int(sid[i]),
                         config.VALIDATION_START, config.VALIDATION_END,
                         _round(d["mae"]), _round(d["rmse"]), _round(d["wmae"]),
                         _round(d["wrmse"]), _round(d["abs_error"]), _round(d["bias"]),
                         28, run_id))
    sql = ("INSERT INTO fact_forecast_evaluation "
           "(model_id, product_surr_id, store_surr_id, validation_start, validation_end, "
           "mae, rmse, wmae, wrmse, abs_error, bias, n_holdout, data_provenance, etl_run_id) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'derived',%s)")
    return batch_executemany(conn, sql, rows)


def _write_final_forecasts(conn, run_id, model_id, selected, pid, sid,
                           final_trail, eval_actual, sigma_eval, stat_eval,
                           pilot_rows, pilot_full, totals):
    sql = ("INSERT INTO fact_forecast "
           "(model_id, product_surr_id, store_surr_id, forecast_origin, forecast_horizon, "
           "forecast_date, forecast_value, lower_bound, upper_bound, is_final, "
           "data_provenance, etl_run_id) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,'derived',%s)")

    # final statistical fits at origin 1941 (fit on [1,1941])
    stat_final = {}
    for i in pilot_rows:
        k = (int(pid[i]), int(sid[i]))
        full = pilot_full.get(k)
        if full is None:
            continue
        for m, fitter in models.STATISTICAL.items():
            res = fitter(full, config.FINAL_HORIZON)
            stat_final[(i, m)] = res.point

    # baseline final forecasts (vectorized)
    baseline_final = {m: models.BASELINES[m](final_trail, config.FINAL_HORIZON)
                      for m in models.BASELINES}

    day0 = config.FINAL_FORECAST_START
    z = config.PI_Z
    fcast_rows = []

    def emit(model_key, i, horizon_step, day, point, sigma):
        if sigma is not None and np.isfinite(sigma):
            lo, hi = metrics.forecast_interval(point, sigma, z)
            lo = max(lo, 0.0)
        else:
            lo, hi = point, point
        fcast_rows.append((model_id[model_key], int(pid[i]), int(sid[i]),
                           config.OBSERVED_END, horizon_step, day,
                           _round(point, 4), _round(lo, 4), _round(hi, 4), run_id))

    for i in range(len(pid)):
        m = selected[i]
        if m in models.BASELINES:
            fc = baseline_final[m][i]
            sigma = sigma_eval[m][i]
            for h in range(config.FINAL_HORIZON):
                emit(m, i, h + 1, day0 + h, float(fc[h]), float(sigma))
        else:
            fc = stat_final.get((i, m))
            if fc is None:
                # fall back: seasonal-naive baseline with its sigma
                fc = baseline_final["seasonal_naive"][i]
                sigma = sigma_eval["seasonal_naive"][i]
                m_use = "seasonal_naive"
            else:
                sigma = metrics.residual_std(
                    stat_eval[m].get(i, np.full(config.VALIDATION_HORIZON, np.nan)))
                m_use = m
            for h in range(config.FINAL_HORIZON):
                emit(m_use, i, h + 1, day0 + h, float(fc[h]), float(sigma))
        if len(fcast_rows) >= 20000:
            batch_executemany(conn, sql, fcast_rows)
            fcast_rows = []
    if fcast_rows:
        batch_executemany(conn, sql, fcast_rows)
    return len(pid) * config.FINAL_HORIZON


if __name__ == "__main__":
    main()
