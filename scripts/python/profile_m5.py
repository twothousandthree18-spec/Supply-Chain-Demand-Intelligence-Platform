"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Data Inventory & Profiling

Builds a dataset inventory and profile for every acquired M5 file. Outputs:

  - reports/m5_inventory.json     (machine-readable inventory)
  - reports/m5_profiling.json     (machine-readable profile statistics)
  - prints a summary to console

This module only OBSERVES the data. It never modifies raw files and never
produces simulated data.

Usage:
  .venv\\Scripts\\python scripts\\python\\profile_m5.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from config_loader import load_config  # noqa: E402   (see scripts/python/config_loader.py)

RAW = REPO_ROOT / "data" / "raw"
REPORTS = REPO_ROOT / "reports"
FIG_DIR = REPO_ROOT / "reports" / "figures" / "diagnostics"


def load(path: Path, **kw) -> pd.DataFrame:
    """Efficient read; sales files are wide (many d_ columns)."""
    return pd.read_csv(path, low_memory=False, **kw)


def profile_sales(path: Path, name: str, last_col: str) -> dict:
    df = load(path)
    id_cols = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
    id_cols = [c for c in id_cols if c in df.columns]
    sales_cols = [c for c in df.columns if c.startswith("d_")]
    sales = df[sales_cols]

    n_products = df["item_id"].nunique()
    n_stores = df["store_id"].nunique()
    combos = df.groupby(["item_id", "store_id"]).ngroups
    total_demand = int(sales.values.sum())
    zero_freq = float((sales.values == 0).mean())
    n_neg = int((sales.values < 0).sum())
    date_start = int(sales_cols[0].replace("d_", ""))
    date_end = int(sales_cols[-1].replace("d_", ""))

    profile = {
        "filename": name,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "id_columns": id_cols,
        "sales_columns": len(sales_cols),
        "product_count": int(n_products),
        "store_count": int(n_stores),
        "item_store_combinations": int(combos),
        "day_columns": [sales_cols[0], sales_cols[-1]],
        "day_start": date_start,
        "day_end": date_end,
        "total_demand": total_demand,
        "zero_demand_fraction": round(zero_freq, 6),
        "negative_value_count": int(n_neg),
        "duplicate_ids": int(df["id"].duplicated().sum()),
        "missing_cells": int(df.isna().sum().sum()),
        "expected_last_day_ok": (sales_cols[-1] == last_col),
    }
    return profile


def _calendar_day_int(series: pd.Series) -> pd.Series:
    """Convert calendar 'd' column to int, stripping any 'd_' prefix."""
    s = series.astype(str).str.replace("d_", "", regex=False)
    return s.astype(int)


def profile_calendar(path: Path) -> dict:
    df = load(path)
    try:
        d_int = _calendar_day_int(df["d"])
    except (ValueError, TypeError):
        d_int = df["d"].astype(int)
    profile = {
        "filename": path.name,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "min_date": str(df["date"].min()),
        "max_date": str(df["date"].max()),
        "duplicate_d": int(df["d"].duplicated().sum()),
        "duplicate_date": int(df["date"].duplicated().sum()),
        "missing_counts": {},
        "event_columns": [c for c in df.columns if c.startswith("event")],
        "snap_columns": [c for c in df.columns if c.startswith("snap")],
    }
    # date continuity
    dates = pd.to_datetime(df["date"])
    full = pd.date_range(dates.min(), dates.max(), freq="D")
    profile["expected_days"] = len(full)
    profile["actual_days"] = int(len(dates))
    profile["date_continuous"] = bool(len(full) == len(dates.drop_duplicates()))
    for c in df.columns:
        profile["missing_counts"][c] = int(df[c].isna().sum())
    # day id continuity (calendar d spans 1..N continuous when sorted)
    profile["day_id_min"] = int(d_int.min())
    profile["day_id_max"] = int(d_int.max())
    profile["day_id_continuous"] = bool(
        len(df) == d_int.nunique() and
        d_int.min() == 1 and d_int.max() == len(df)
    )
    return profile


def profile_prices(path: Path) -> dict:
    df = load(path)
    weeks = sorted(pd.unique(df["wm_yr_wk"]))
    profile = {
        "filename": path.name,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "duplicate_rows": int(df.duplicated().sum()),
        "duplicate_keys": int(df.duplicated(["item_id", "store_id", "wm_yr_wk"]).sum()),
        "item_count": int(df["item_id"].nunique()),
        "store_count": int(df["store_id"].nunique()),
        "unique_weeks": len(weeks),
        "week_min": weeks[0],
        "week_max": weeks[-1],
        "sell_price_missing": int(df["sell_price"].isna().sum()),
        "sell_price_min": float(df["sell_price"].min()),
        "sell_price_max": float(df["sell_price"].max()),
        "sell_price_mean": float(df["sell_price"].mean()),
        "sell_price_negative": int((df["sell_price"] < 0).sum()),
        "sell_price_zero": int((df["sell_price"] == 0).sum()),
    }
    return profile


def profile_sales_train(path: Path) -> dict:
    df = load(path)
    return {
        "filename": path.name,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "expected_rows_30490": int(len(df) == 30490),
        "columns": list(df.columns[:6]) + [f"d_{i}" for i in (1, 1913, 1941)],
    }


def main():
    REPORTS.mkdir(exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    core = cfg["m5"]["core_files"]

    results = {}
    missing = []
    for f in core:
        p = RAW / f
        if not p.exists():
            missing.append(f)
            continue
        if f == "calendar.csv":
            results[f] = profile_calendar(p)
        elif f == "sell_prices.csv":
            results[f] = profile_prices(p)
        elif f == "sales_train_validation.csv":
            results[f] = profile_sales(
                p, f, cfg["m5"]["last_sales_col_validation"])
        elif f == "sales_train_evaluation.csv":
            results[f] = profile_sales(
                p, f, cfg["m5"]["last_sales_col_evaluation"])

    out = {
        "project": cfg["project"],
        "phase": 1,
        "files": results,
        "missing_files": missing,
    }
    with open(REPORTS / "m5_profiling.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)

    print("=== M5 Profiling Summary ===")
    if missing:
        print("MISSING FILES (run scripts/acquire_m5.py first):", missing)
        sys.exit(1)
    for name, prof in results.items():
        print(f"\n[{name}]")
        for k, v in prof.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
