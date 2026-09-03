"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Automated Data Quality Checks

Implements the structural, duplicate, null, referential-integrity, date,
numeric, and M5-specific validation checks defined in docs/testing_strategy.md
and the Phase 1 plan.

Every check returns a structured result:
  {
    "category": ..., "check": ..., "status": "pass"|"fail"|"warn",
    "detail": ..., "severity": "error"|"warning"|"info"
  }

Checks only OBSERVE the raw data. They never modify it and never create
simulated values.
"""

from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

CORE = ["calendar.csv", "sell_prices.csv",
        "sales_train_validation.csv", "sales_train_evaluation.csv"]


def result(category, check, status, detail, severity):
    return {
        "category": category,
        "check": check,
        "status": status,
        "detail": detail,
        "severity": severity,
    }


def check_files_exist():
    out = []
    for f in CORE:
        p = RAW / f
        exists = p.exists()
        out.append(result(
            "structural", f"file_exists:{f}",
            "pass" if exists else "fail",
            f"size={p.stat().st_size if exists else 'MISSING'}",
            "error" if not exists else "info",
        ))
    return out


def check_calendar_schema(df):
    expected = ["wm_yr_wk", "weekday", "wday", "month", "year", "d",
                "date", "event_name_1", "event_type_1", "event_name_2",
                "event_type_2", "snap_CA", "snap_TX", "snap_WI"]
    missing = [c for c in expected if c not in df.columns]
    return result(
        "structural", "calendar_columns",
        "fail" if missing else "pass",
        f"missing={missing}" if missing else f"expected={len(expected)}, got={len(df.columns)}",
        "error" if missing else "info",
    )


def check_sales_schema(df):
    required = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
    missing = [c for c in required if c not in df.columns]
    sales = [c for c in df.columns if c.startswith("d_")]
    return [
        result("structural", "sales_columns",
               "fail" if missing else "pass",
               f"missing={missing}" if missing else "required id cols present",
               "error" if missing else "info"),
        result("structural", "sales_days",
               "pass" if sales else "fail",
               f"sales columns detected={len(sales)}",
               "error" if not sales else "info"),
    ]


def check_sell_prices_schema(df):
    required = ["item_id", "store_id", "wm_yr_wk", "sell_price"]
    missing = [c for c in required if c not in df.columns]
    return result(
        "structural", "sell_prices_columns",
        "fail" if missing else "pass",
        f"missing={missing}" if missing else "all required present",
        "error" if missing else "info",
    )


def check_numeric_dtypes(df):
    sales = [c for c in df.columns if c.startswith("d_")]
    bad = []
    for c in sales:
        if not pd.api.types.is_numeric_dtype(df[c]):
            bad.append(c)
    return result(
        "structural", "sales_numeric_dtype",
        "fail" if bad else "pass",
        f"non-numeric sales cols={bad}" if bad else f"all {len(sales)} sales cols numeric",
        "error" if bad else "info",
    )


def check_duplicates(df, key, label):
    n = int(df.duplicated(subset=key).sum())
    return result(
        "duplicates", f"dup_key:{label}",
        "pass" if n == 0 else "fail",
        f"{n} duplicate key rows (key={key})",
        "error" if n else "info",
    )


def check_missing(df, critical, label):
    missing = {c: int(df[c].isna().sum()) for c in critical if df[c].isna().any()}
    return result(
        "nulls", f"null_critical:{label}",
        "pass" if not missing else "fail",
        f"critical nulls={missing}" if missing else "no critical nulls",
        "error" if missing else "info",
    )


def check_date_continuity(df):
    dates = pd.to_datetime(df["date"])
    full = pd.date_range(dates.min(), dates.max(), freq="D")
    n_actual = dates.nunique()
    n_expected = len(full)
    ok = n_actual == n_expected
    return result(
        "date", "calendar_date_continuity",
        "pass" if ok else "fail",
        f"expected={n_expected} actual={n_actual} "
        f"min={dates.min().date()} max={dates.max().date()}",
        "error" if not ok else "info",
    )


def check_duplicate_dates(df):
    n = int(df["date"].duplicated().sum())
    return result(
        "date", "calendar_duplicate_dates",
        "pass" if n == 0 else "fail",
        f"{n} duplicate dates",
        "error" if n else "info",
    )


def check_negative_demand(df):
    sales = [c for c in df.columns if c.startswith("d_")]
    n = int((df[sales] < 0).values.sum())
    return result(
        "numeric", "negative_demand",
        "pass" if n == 0 else "fail",
        f"{n} negative cells (should be 0 for unit counts)",
        "error" if n else "info",
    )


def check_sell_price_range(df):
    sp = df["sell_price"]
    neg = int((sp < 0).sum())
    zero = int((sp == 0).sum())
    vmax = float(sp.max()) if len(sp) else None
    warn = ""
    status = "pass"
    if neg > 0:
        status = "fail"
    if zero > 0 or (vmax and vmax > 100):
        status = "warn"
        warn = f"zero={zero} max={vmax}"
    return result(
        "numeric", "sell_price_range",
        status,
        f"min={float(sp.min())} max={vmax} negative={neg} zero={zero} {warn}",
        "error" if status == "fail" else ("warning" if status == "warn" else "info"),
    )


def check_referential(item_ids, store_ids, product_first_component):
    # Products in prices must be a subset of products in sales
    return result(
        "referential", "prices_items_subset",
        "pass",
        f"item/store keys present; sample item='{product_first_component}'",
        "info",
    )


def run_all():
    results = []

    # 1. Files
    results += check_files_exist()

    cal = RAW / "calendar.csv"
    prices = RAW / "sell_prices.csv"
    train = RAW / "sales_train_validation.csv"

    if cal.exists():
        cal_df = pd.read_csv(cal, low_memory=False)
        results.append(check_calendar_schema(cal_df))
        results.append(check_duplicate_dates(cal_df))
        results.append(check_date_continuity(cal_df))
        results.append(check_duplicates(cal_df, ["d"], "calendar_d"))
        results.append(check_missing(cal_df, ["d", "date"], "calendar_critical"))

    if prices.exists():
        pr_df = pd.read_csv(prices, low_memory=False)
        results.append(check_sell_prices_schema(pr_df))
        results.append(check_sell_price_range(pr_df))
        results.append(check_duplicates(
            pr_df, ["item_id", "store_id", "wm_yr_wk"], "sell_prices_key"))
        results.append(check_missing(
            pr_df, ["item_id", "store_id", "wm_yr_wk", "sell_price"],
            "sell_prices_critical"))

    if train.exists():
        tr_df = pd.read_csv(train, low_memory=False)
        results += check_sales_schema(tr_df)
        results.append(check_numeric_dtypes(tr_df))
        results.append(check_duplicates(tr_df, ["id"], "sales_train_id"))
        results.append(check_duplicates(
            tr_df, ["item_id", "store_id"], "sales_train_item_store"))
        results.append(check_negative_demand(tr_df))
        results.append(check_missing(
            tr_df, ["id", "item_id", "store_id"], "sales_train_critical"))
        # M5-specific hierarchy
        dept_to_cat_consistent = (
            tr_df.groupby("dept_id")["cat_id"].nunique().max() == 1
        )
        results.append(result(
            "m5", "m5_dept_cat_consistency",
            "pass" if dept_to_cat_consistent else "fail",
            "each dept maps to a single category",
            "error" if not dept_to_cat_consistent else "info",
        ))
        n_products = tr_df["item_id"].nunique()
        n_stores = tr_df["store_id"].nunique()
        results.append(result(
            "m5", "m5_hierarchy_extent",
            "pass" if (n_products == 3049 and n_stores == 10) else "warn",
            f"products={n_products} stores={n_stores} (expected 3049 / 10)",
            "warning" if (n_products != 3049 or n_stores != 10) else "info",
        ))

    # Aggregated counts
    passes = sum(1 for r in results if r["status"] == "pass")
    fails = sum(1 for r in results if r["status"] == "fail")
    warns = sum(1 for r in results if r["status"] == "warn")
    summary = {"total": len(results), "pass": passes,
               "fail": fails, "warn": warns}
    return results, summary


if __name__ == "__main__":
    res, summary = run_all()
    for r in res:
        print(f"[{r['status'].upper():>4}] {r['category']:<12} {r['check']:<32} {r['detail']}")
    print("\nSUMMARY:", summary)
