"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Diagnostic Data Exploration

Creates a LIMITED set of diagnostic charts for data-quality/profiling purposes
(NOT final portfolio visuals). Uses matplotlib only.

Charts are written to reports/figures/diagnostics/.

Usage:
  .venv\\Scripts\\python scripts\\python\\diagnose_m5.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "python"))
from config_loader import load_config  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAW = REPO_ROOT / "data" / "raw"
OUT = REPO_ROOT / "reports" / "figures" / "diagnostics"

# Design-system tokens (Obsidian / Deep Jade / Electric Jade / Champagne / Soft White)
OBS = "#090B0A"
JADE = "#123C35"
ELECTRIC = "#19E6B1"
CHAMP = "#D8C39B"
WHITE = "#EDEFEA"


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=120, facecolor=WHITE)
    plt.close(fig)
    print("saved:", OUT / name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    train = RAW / "sales_train_validation.csv"
    cal = RAW / "calendar.csv"
    pr = RAW / "sell_prices.csv"

    # --- Demand over time (daily aggregate) ---
    if train.exists():
        df = pd.read_csv(train, low_memory=False)
        dcols = [c for c in df.columns if c.startswith("d_")]
        daily = df[dcols].sum(axis=0)
        daily.index = pd.RangeIndex(1, len(daily) + 1)
        fig, ax = plt.subplots(figsize=(10, 3), dpi=120)
        ax.plot(daily.index, daily.values, color=JADE, lw=0.8)
        ax.set_title("Daily total demand (diagnostic)", color=OBS)
        ax.set_facecolor(WHITE)
        save(fig, "demand_over_time.png")

        # --- Demand distribution ---
        flat = df[dcols].values
        fig, ax = plt.subplots(figsize=(6, 3.5), dpi=120)
        ax.hist(flat[flat > 0].ravel(), bins=60, color=ELECTRIC, log=True)
        ax.set_title("Demand value distribution (>0, log scale)", color=OBS)
        ax.set_facecolor(WHITE)
        save(fig, "demand_distribution.png")

        # --- Sparsity: fraction of zero-demand product/store days ---
        zero_frac = (df[dcols] == 0).mean(axis=1)
        fig, ax = plt.subplots(figsize=(6, 3.5), dpi=120)
        ax.hist(zero_frac, bins=40, color=CHAMP, edgecolor=OBS)
        ax.set_title("Zero-demand fraction per product/store (diagnostic)", color=OBS)
        ax.set_xlabel("fraction of days with zero demand")
        ax.set_facecolor(WHITE)
        save(fig, "demand_sparsity.png")

        # --- Missingness summary ---
        miss = df.isna().sum()
        if miss.sum() > 0:
            miss = miss[miss > 0].sort_values(ascending=False)
            fig, ax = plt.subplots(figsize=(6, 3.5), dpi=120)
            ax.bar(range(len(miss)), miss.values, color=OBS)
            ax.set_xticks(range(len(miss)))
            ax.set_xticklabels(miss.index, rotation=90, fontsize=6)
            ax.set_title("Missing values by column (diagnostic)", color=OBS)
            ax.set_facecolor(WHITE)
            save(fig, "missingness_summary.png")
        else:
            print("no missing values in sales_train_validation - skipped chart")

    # --- Price distribution ---
    if pr.exists():
        prices = pd.read_csv(pr, low_memory=False)["sell_price"]
        fig, ax = plt.subplots(figsize=(6, 3.5), dpi=120)
        ax.hist(prices, bins=60, color=CHAMP, edgecolor=OBS)
        ax.set_title("Selling price distribution (diagnostic)", color=OBS)
        ax.set_facecolor(WHITE)
        save(fig, "price_distribution.png")

    # --- Calendar coverage / event presence ---
    if cal.exists():
        cdf = pd.read_csv(cal, low_memory=False)
        cdf["date"] = pd.to_datetime(cdf["date"])
        has_event = cdf["event_name_1"].notna()
        fig, ax = plt.subplots(figsize=(10, 3), dpi=120)
        ts = pd.Series(has_event.values, index=cdf["date"])
        ax.bar(ts.index, ts.values, width=1, color=ELECTRIC)
        ax.set_title("Calendar days with events (diagnostic)", color=OBS)
        ax.set_facecolor(WHITE)
        save(fig, "calendar_events.png")

    print("\nDiagnostic charts complete.")


if __name__ == "__main__":
    main()
