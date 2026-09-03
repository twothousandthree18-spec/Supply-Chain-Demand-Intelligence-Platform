"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Data Quality Tests (pytest)

Runs the automated quality checks against the acquired M5 raw data and
asserts expectations that define the Phase 1 acceptance criteria.

These tests REQUIRE the raw data to be present (run scripts/acquire_m5.py
first). If data is absent they fail loudly rather than silently pass.

Usage:
  .venv\\Scripts\\python -m pytest tests/data -q
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from validation import quality_checks as qc  # noqa: E402

RAW = REPO_ROOT / "data" / "raw"


def _require(fname):
    p = RAW / fname
    assert p.exists(), f"{fname} missing - run scripts/acquire_m5.py"
    return pd.read_csv(p, low_memory=False)


# ---- Structural ----

def test_all_core_files_exist():
    res = qc.check_files_exist()
    fails = [r for r in res if r["status"] == "fail"]
    assert not fails, fails


def test_sales_schema():
    df = _require("sales_train_validation.csv")
    res = qc.check_sales_schema(df)
    assert all(r["status"] == "pass" for r in res), res


def test_sales_numeric_dtype():
    df = _require("sales_train_validation.csv")
    assert qc.check_numeric_dtypes(df)["status"] == "pass"


def test_calendar_schema():
    df = _require("calendar.csv")
    assert qc.check_calendar_schema(df)["status"] == "pass"


def test_sell_prices_schema():
    df = _require("sell_prices.csv")
    assert qc.check_sell_prices_schema(df)["status"] == "pass"


# ---- Order of magnitude / known M5 constants ----

def test_sales_row_count():
    df = _require("sales_train_validation.csv")
    assert len(df) == 30490, f"expected 30490 rows, got {len(df)}"


def test_m5_product_store_counts():
    df = _require("sales_train_validation.csv")
    assert df["item_id"].nunique() == 3049
    assert df["store_id"].nunique() == 10


def test_sales_day_columns():
    df = _require("sales_train_validation.csv")
    sales = [c for c in df.columns if c.startswith("d_")]
    assert sales and sales[0] == "d_1" and sales[-1] == "d_1913"


# ---- Duplicates ----

def test_no_duplicate_sales_id():
    df = _require("sales_train_validation.csv")
    assert df["id"].is_unique


def test_no_duplicate_calendar_days():
    df = _require("calendar.csv")
    assert df["d"].is_unique and df["date"].is_unique


def test_no_duplicate_price_key():
    prices = _require("sell_prices.csv")
    n = prices.duplicated(["item_id", "store_id", "wm_yr_wk"]).sum()
    assert n == 0, f"{n} duplicate price keys"


# ---- Nulls ----

def test_no_critical_nulls():
    for f, critical in [
        ("sales_train_validation.csv", ["id", "item_id", "store_id"]),
        ("calendar.csv", ["d", "date"]),
        ("sell_prices.csv", ["item_id", "store_id", "wm_yr_wk", "sell_price"]),
    ]:
        df = _require(f)
        assert qc.check_missing(df, critical, "x")["status"] == "pass"


def test_no_negative_demand():
    df = _require("sales_train_validation.csv")
    assert qc.check_negative_demand(df)["status"] == "pass"


def test_sell_price_range_reasonable():
    # Real M5 data contains items priced above $100 (observed max = 107.32).
    # Assert non-negative and a defensible sanity ceiling (no absurd prices),
    # and that the observed maximum is within retail-plausible bounds.
    prices = _require("sell_prices.csv")
    assert (prices["sell_price"] >= 0).all()
    assert (prices["sell_price"] > 0).all()      # no free/zero-priced items
    assert (prices["sell_price"] < 1000).all()   # no absurd prices
    assert prices["sell_price"].max() <= 120     # observed max is ~107.32


# ---- Date continuity ----

def test_calendar_date_continuity():
    df = _require("calendar.csv")
    assert qc.check_date_continuity(df)["status"] == "pass"


# ---- Referential consistency ----

def test_price_items_subset_of_sales_items():
    prices = _require("sell_prices.csv")
    sales = _require("sales_train_validation.csv")
    price_items = set(prices["item_id"])
    sales_items = set(sales["item_id"])
    assert price_items <= sales_items, "prices contain items not in sales"
    assert len(price_items) == 3049


def test_price_store_subset_of_sales_stores():
    prices = _require("sell_prices.csv")
    sales = _require("sales_train_validation.csv")
    assert set(prices["store_id"]) <= set(sales["store_id"])


# ---- M5-specific hierarchy ----

def test_dept_cat_consistency():
    df = _require("sales_train_validation.csv")
    assert df.groupby("dept_id")["cat_id"].nunique().max() == 1


def test_m5_hierarchy_warnings_only():
    df = _require("sales_train_validation.csv")
    assert df["item_id"].nunique() == 3049
    assert df["store_id"].nunique() == 10
    assert df["state_id"].nunique() == 3
    assert set(df["state_id"]) == {"CA", "TX", "WI"}
