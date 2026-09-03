"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Data Quality Validation Runner

Runs automated checks (structural, duplicates, nulls, referential integrity,
date, numeric, M5-specific) and writes a JSON results file plus console summary.

Usage:
  .venv\\Scripts\\python scripts\\python\\validate_m5.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "python"))

from validation import quality_checks  # noqa: E402
from config_loader import load_config  # noqa: E402


def main():
    cfg = load_config()
    results, summary = quality_checks.run_all()

    report = {
        "project": cfg["project"],
        "phase": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "checks": results,
    }

    out_path = REPO_ROOT / "reports" / "m5_quality_checks.json"
    REPO_ROOT.joinpath("reports").mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {out_path}")

    print("\n=== Data Quality Check Results ===")
    for r in results:
        print(f"[{r['status'].upper():>4}] {r['category']:<12} "
              f"{r['check']:<34} {r['detail']}")
    print(f"\nSUMMARY: {summary['pass']} pass, {summary['fail']} fail, "
          f"{summary['warn']} warn (of {summary['total']})")

    if summary["fail"]:
        print("\nNOTE: failures detected. Review reports/m5_quality_checks.json.")
        sys.exit(1)
    print("\nResult: PASS (no failing checks)")


if __name__ == "__main__":
    main()
