"""
Phase 5 - Step 2 dashboard-page validation harness (read-only).

Validates the seven page build specifications and their supporting registries
(dashboards/powerbi/pages/*) against the LOCKED model contract and warehouse:

  * every page spec file exists (P1..P7 + SHARED_CONTRACT)
  * every page references only known semantic-model tables (from POWERBI_MODEL.md)
  * every measure named on a page exists in DAX_MEASURES.dax
  * page reconcile anchors (grains/ranks/horizons) match verified locked DB facts
  * hard rules: no fact_daily_sales reference; day-grain pages are horizon-bounded;
    provenance matches (derived vs simulated); pilot rule on P3; empty-state rule on P6

Read-only: never DDL/DML/ETL. No full scan of fact_daily_sales.
"""

import re
import sys
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "sql"))

from src.etl.db_utils import connect  # noqa: E402

PAGES_DIR = REPO_ROOT / "dashboards" / "powerbi" / "pages"
DAX_FILE = REPO_ROOT / "dashboards" / "powerbi" / "DAX_MEASURES.dax"


@pytest.fixture(scope="session")
def conn():
    c = connect()
    yield c
    c.close()


def _scalar(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


_DAX_KEYWORDS = {
    "VAR", "IF", "SUM", "SUMX", "AVERAGE", "AVERAGEX", "DIVIDE", "CALCULATE",
    "FILTER", "MAX", "MIN", "SELECTEDVALUE", "RETURN", "COUNTROWS", "VALUES",
    "ALL", "ALLNOBLANKROW", "OR", "AND", "NOT", "BLANK", "DISTINCT", "TOPN",
}


def _dax_heading_names():
    """Column-0 measure declarations in the DAX file.

    A measure declaration is a non-comment line that starts at column 0 with a
    letter and contains '='. Continuation/VAR lines are indented, so they are
    excluded. Reserved expression keywords are filtered out.
    """
    names = set()
    for line in DAX_FILE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith((" ", "\t", "/", "//", "*")):
            m = re.match(r"^([A-Za-z][A-Za-z0-9 _%/]*?)\s*=\s*", line)
            if m:
                name = m.group(1).strip()
                if name not in _DAX_KEYWORDS:
                    names.add(name)
    return names


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _known_model_tables():
    """Names in POWERBI_MODEL.md written as **TableName** (or **`TableName`**)."""
    text = (REPO_ROOT / "dashboards" / "powerbi" / "POWERBI_MODEL.md").read_text(encoding="utf-8")
    tables = set()
    for m in re.finditer(r"\*\*`?([A-Za-z][A-Za-z0-9_]*)`?\*\*", text):
        tables.add(m.group(1))
    return tables


# --------------------------------------------------------------------------- #
# Locked facts (verified Phase 1-4 / Step 1)
# --------------------------------------------------------------------------- #
LOCKED = {
    "units": 66_927_173,
    "scenario_grain": 213_430,
    "analysis_grain": 30_490,
    "seasonality_grain": 359_181,
    "forecast_grain": 853_720,
    "evaluation_grain": 122_088,
    "inventory_grain": 853_720,
    "horizon_start": 1942,
    "horizon_end": 1969,
    "scenario_comparison_grain": 0,
    "risk_rank_per_run": 30_490,
}

YEAR, MONTH, DAY = 1942, 1969, 28  # horizon anchors


# --------------------------------------------------------------------------- #
# Artifact presence
# --------------------------------------------------------------------------- #
def test_all_page_spec_files_exist():
    for p in ["P1_Executive_Overview.md", "P2_Demand_Overview.md",
              "P3_Forecast_Performance.md", "P4_Inventory_Risk.md",
              "P5_Stockout_Excess_Risk.md", "P6_Scenario_Comparison.md",
              "P7_Prioritized_Operational_Insights.md", "SHARED_CONTRACT.md",
              "filters_registry.json", "formatting_registry.json",
              "page_map_registry.json"]:
        assert (PAGES_DIR / p).exists(), f"missing page artifact: {p}"


def test_page_map_registry_is_complete():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    assert reg["pages_order"] == ["P1_Executive_Overview", "P2_Demand_Overview",
                                  "P3_Forecast_Performance", "P4_Inventory_Risk",
                                  "P5_Stockout_Excess_Risk", "P6_Scenario_Comparison",
                                  "P7_Prioritized_Operational_Insights"]
    assert set(reg["pages"]) == set(reg["pages_order"])
    for name in reg["pages_order"]:
        assert (PAGES_DIR / f"{name}.md").exists()


# --------------------------------------------------------------------------- #
# Model-table / measure reference integrity
# --------------------------------------------------------------------------- #
def test_page_tables_are_known_model_tables():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    known = _known_model_tables()
    assert known, "no model tables discovered in POWERBI_MODEL.md"
    for name, info in reg["pages"].items():
        for t in info["model_tables"]:
            assert t in known, f"{name} references unknown model table {t}"


def test_page_measures_exist_in_dax():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    da = _dax_heading_names()
    assert da, "no DAX measures parsed"
    for name, info in reg["pages"].items():
        for m in info["measures_used"]:
            assert m in da, f"{name} uses measure not defined in DAX: {m}"


# --------------------------------------------------------------------------- #
# Hard rules
# --------------------------------------------------------------------------- #
def test_no_page_references_fact_daily_sales():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    for name, info in reg["pages"].items():
        joined = " ".join(info["model_tables"])
        assert "fact_daily_sales" not in joined.lower() and "FactDailySales" not in joined, \
            f"{name} must not reference fact_daily_sales in model_tables"
    # page prose may only MENTION the guard negatively; flag only a positive
    # procedural directive (e.g., "load/bind/scan fact_daily_sales to build X")
    dangerous = ("bind to fact_daily_sales", "load fact_daily_sales",
                 "read from fact_daily_sales", "select from fact_daily_sales",
                 "scan fact_daily_sales", "fact_daily_sales is used",
                 "import fact_daily_sales", "fact_daily_sales into the model")
    for md in PAGES_DIR.glob("P*.md"):
        low = md.read_text(encoding="utf-8").lower()
        for d in dangerous:
            assert d not in low, f"{md.name} has positive fact_daily_sales directive: {d}"


def test_day_grain_pages_are_horizon_bounded():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    for name, info in reg["pages"].items():
        if info["bounded_day_horizon"]:
            txt = (PAGES_DIR / f"{name}.md").read_text(encoding="utf-8")
            assert "28-" in txt or "1942" in txt or "1969" in txt, \
                f"{name} is day-grain but does not state the 28-day horizon"
        else:
            txt = (PAGES_DIR / f"{name}.md").read_text(encoding="utf-8")
            assert "bounded to the 28-day" not in txt, \
                f"{name} claims day-grain bound but registry says non-horizon (misconfig)"


def test_provenance_consistency():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    # derived-only pages: P2, P3 (forecast/seasonality/demand). simulated pages: P4,P5,P6,P7.
    expect_derived = {"P2_Demand_Overview", "P3_Forecast_Performance"}
    expect_simulated = {"P4_Inventory_Risk", "P5_Stockout_Excess_Risk",
                        "P6_Scenario_Comparison", "P7_Prioritized_Operational_Insights"}
    for name, info in reg["pages"].items():
        prov = set(info["provenance"])
        if name in expect_derived:
            assert prov == {"derived"}, f"{name} expected derived-only provenance, got {prov}"
        if name in expect_simulated:
            assert prov == {"simulated"}, f"{name} expected simulated-only provenance, got {prov}"
    # P1 is mixed (revenue derived + inventory snapshot simulated)
    assert set(reg["pages"]["P1_Executive_Overview"]["provenance"]) == {"derived", "simulated"}


def test_pilot_rule_present_on_p3():
    txt = (PAGES_DIR / "P3_Forecast_Performance.md").read_text(encoding="utf-8")
    assert "pilot" in txt.lower() and "30,490" in txt, \
        "P3 must speak to the ETS/SARIMA 64-series pilot (no full-support implication)"


def test_empty_state_rule_present_on_p6():
    reg = _load_json(PAGES_DIR / "page_map_registry.json")
    p6txt = (PAGES_DIR / "P6_Scenario_Comparison.md").read_text(encoding="utf-8")
    assert "0 rows" in p6txt or "empty" in p6txt.lower() or "tradeoff" in p6txt.lower(), \
        "P6 must explicitly handle fact_scenario_comparison = 0 rows empty state"
    assert reg["pages"]["P6_Scenario_Comparison"]["empty_state_fact_comparison"] is True


def test_undefined_dash_rule_present():
    for md in PAGES_DIR.glob("P*.md"):
        txt = md.read_text(encoding="utf-8")
        assert ("—" in txt or "Display Dash" in txt or "undefined" in txt.lower() or
                "BLANK" in txt), \
            f"{md.name} must document the undefined-dash rule"


# --------------------------------------------------------------------------- #
# Reconcile anchors vs locked DB (read-only SELECTs, small/aggregate only)
# --------------------------------------------------------------------------- #
def test_reconcile_anchors_match_db(conn):
    cur = conn.cursor()
    reg = _load_json(PAGES_DIR / "page_map_registry.json")

    rows = {}
    rows["units"] = _scalar(cur, "SELECT SUM(units) FROM mv_weekly_sales")
    rows["scenario_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_scenario_result")
    rows["analysis_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_demand_analysis")
    rows["seasonality_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_demand_seasonality")
    rows["forecast_grain"] = _scalar(cur,
        "SELECT COUNT(*) FROM fact_forecast WHERE is_final = TRUE")
    rows["evaluation_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_forecast_evaluation")
    rows["inventory_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_inventory_simulation")
    rows["scenario_comparison_grain"] = _scalar(cur, "SELECT COUNT(*) FROM fact_scenario_comparison")
    rows["horizon_start"] = _scalar(cur,
        "SELECT MIN(forecast_date) FROM fact_forecast WHERE is_final = TRUE")
    rows["horizon_end"] = _scalar(cur,
        "SELECT MAX(forecast_date) FROM fact_forecast WHERE is_final = TRUE")
    rows["risk_rank_per_run"] = _scalar(cur,
        "SELECT COUNT(DISTINCT risk_rank) FROM fact_scenario_result "
        "WHERE scenario_run_id IN (6, 7)")
    cur.close()

    for page_name in reg["pages_order"]:
        for anchor, val in reg["pages"][page_name]["reconcile_anchors"].items():
            assert rows[anchor] == val, (
                f"page {page_name} anchor {anchor}: registry={val} DB={rows[anchor]}")

    # extra invariant: risk_rank uniqueness per rank run 1..30,490
    cur = conn.cursor()
    dup = _scalar(cur,
        "SELECT COUNT(*) - COUNT(DISTINCT risk_rank) FROM fact_scenario_result "
        "WHERE scenario_run_id = 6")
    assert dup == 0, "stockout rank run must have no duplicate risk_rank (no ties)"
    cur.close()