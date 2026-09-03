"""
Phase 6 - Step 6 validation harness (Scenario + Risk Intelligence pages).

Covers the build contracts delivered for the two product-area pages:

  * shell exposes the Scenario and Risk views with filter bars + section
    containers and correct nav wiring
  * app.js renders all required sections and wires server-side filters,
    pagination, ranking switching, and risk-driver drill-down
  * scenario correctness: baseline + simulation scenarios are shown with
    vs-baseline deltas; ranking scenarios carry no deltas ("—"); the locked
    empty action-tradeoff comparison is surfaced explicitly and never fabricated
  * risk correctness: rankings are deterministic by native risk_rank (1..30,490),
    server-side filtered/paginated, dimension drill-down (dept/category/state/
    region), and a per-series drivers endpoint feeds the detail panel
  * provenance: all scenario/risk figures are simulated
  * undefined values render literal "—"
  * source-level enforcement: no fact_daily_sales / v_units access from src/web

These are read-only tests against the locked warehouse (no writes).
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from src.web.main import app  # noqa: E402

client = TestClient(app)

WEB_SRC = REPO_ROOT / "src" / "web"
INDEX_HTML = (WEB_SRC / "static" / "index.html").read_text(encoding="utf-8")
APP_JS = (WEB_SRC / "static" / "js" / "app.js").read_text(encoding="utf-8")
BASE_CSS = (WEB_SRC / "static" / "css" / "base.css").read_text(encoding="utf-8")

LOCKED_PALETTE = {
    "Obsidian": "#090B0A",
    "Deep Jade": "#123C35",
    "Electric Jade": "#19E6B1",
    "Champagne": "#D8C39B",
    "Soft White": "#EDEFEA",
}

REAL_SERIES = "HOUSEHOLD_1_054:WI_3"


def _all_python_files():
    return list(WEB_SRC.rglob("*.py"))


def _source_text():
    parts = []
    for f in _all_python_files():
        parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Shell / page structure
# --------------------------------------------------------------------------- #
def test_two_views_exist_with_sections():
    assert 'id="view-scenario"' in INDEX_HTML
    assert 'id="view-risk"' in INDEX_HTML
    for sid in ("scenario-status", "scenario-deltas", "scenario-comparison"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing scenario section {sid}"
    for sid in ("risk-distribution", "risk-table", "risk-driver"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing risk section {sid}"


def test_nav_links_to_both_views():
    assert 'data-view="scenario"' in INDEX_HTML
    assert 'data-view="risk"' in INDEX_HTML


def test_demand_filter_bars_present():
    for sid in ("sc-type", "sc-name", "sc-reset"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing scenario filter {sid}"
    for sid in ("rk-type", "rk-tier", "rk-department", "rk-category", "rk-state",
                "rk-store", "rk-product", "rk-topn", "rk-reset"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing risk filter {sid}"


# --------------------------------------------------------------------------- #
# app.js renderers + endpoint usage
# --------------------------------------------------------------------------- #
def test_js_dispatch_and_renderers_present():
    assert "loadScenario" in APP_JS
    assert "loadRisk" in APP_JS
    for fn in ("renderScenarioStatus", "renderScenarioDeltas", "renderScenarioComparison"):
        assert f"function {fn}" in APP_JS, f"missing scenario renderer {fn}"
    for fn in ("renderRiskDistribution", "renderRiskTable", "renderRiskDriver"):
        assert f"function {fn}" in APP_JS, f"missing risk renderer {fn}"


def test_js_uses_exact_scenario_endpoints():
    assert '"/api/scenario/runs"' in APP_JS
    assert '"/api/scenario/deltas"' in APP_JS
    assert '"/api/scenario/comparison"' in APP_JS


def test_js_uses_exact_risk_endpoints():
    assert "/api/risk/rankings?" in APP_JS
    assert "/api/risk/drivers?series=" in APP_JS


def test_js_parallel_load_for_scenario_and_risk():
    # The three scenario endpoints are loaded together in one Promise.all block.
    m = re.search(r"Promise\.all\(\[(.*?)\]\)", APP_JS, re.S)
    blocks = [b for b in re.findall(r"Promise\.all\(\[(.*?)\]\)", APP_JS, re.S)]
    assert any(all(u in b for u in ("/api/scenario/runs", "/api/scenario/deltas", "/api/scenario/comparison")) for b in blocks), (
        "scenario runs/deltas/comparison must load in one Promise.all"
    )


def test_js_does_not_load_all_scenario_rows():
    # No unbounded full-table fetch of scenario result rows.
    assert "/api/scenario/result" not in APP_JS
    assert "superset_rows" not in APP_JS


# --------------------------------------------------------------------------- #
# Scenario endpoints: runs, deltas, comparison empty-state
# --------------------------------------------------------------------------- #
def test_scenario_runs_endpoint():
    r = client.get("/api/scenario/runs")
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 7
    names = {x["scenario_name"] for x in j["runs"]}
    assert {"baseline", "demand_shock_p20", "lead_time_plus_2d",
            "service_level_99", "reorder_policy_alt",
            "stockout_risk_rank", "excess_risk_rank"} <= names
    for run in j["runs"]:
        assert run["provenance"] == "simulated"


def test_scenario_deltas_exclude_baseline_and_null_for_ranking_runs():
    r = client.get("/api/scenario/deltas")
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 6
    names = {x["name"] for x in j["deltas"]}
    assert "baseline" not in names
    for d in j["deltas"]:
        assert d["provenance"] == "simulated"
        assert d["series_count"] == 30490
        if d["scenario_type"] in ("stockout_risk_prioritization", "excess_inventory_prioritization"):
            assert d["delta_service_level"] is None
            assert d["delta_stockout_days"] is None
        else:
            assert d["delta_service_level"] is not None


def test_scenario_comparison_is_explicit_empty_state():
    r = client.get("/api/scenario/comparison")
    assert r.status_code == 200
    j = r.json()
    assert j["present"] is False
    assert j["rows"] == 0
    assert "comparison" in (j["reason"] or "").lower()


def test_js_surfaces_empty_comparison_phrase():
    assert "No action-tradeoff comparison is currently available" in APP_JS


def test_js_disclaims_fabricated_recommendations():
    assert "fact_replenishment_recommendation" in APP_JS
    assert "0 rows" in APP_JS


# --------------------------------------------------------------------------- #
# Risk endpoints: deterministic ranking, filters, pagination, driver detail
# --------------------------------------------------------------------------- #
def test_risk_rankings_deterministic_and_bounded():
    r = client.get("/api/risk/rankings", params={"risk_type": "stockout", "page_size": 50})
    assert r.status_code == 200
    j = r.json()
    assert j["risk_type"] == "stockout"
    assert j["pagination"]["total"] == 30490
    ranks = [x["risk_rank"] for x in j["items"]]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert all(x["provenance"] == "simulated" for x in j["items"])


def test_risk_rankings_excess_type_switching():
    r = client.get("/api/risk/rankings", params={"risk_type": "excess", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert j["risk_type"] == "excess"
    assert j["pagination"]["total"] == 30490


def test_risk_rankings_dimension_filters():
    r = client.get("/api/risk/rankings", params={"risk_type": "stockout", "department": "FOODS_2", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert 0 < j["pagination"]["total"] < 30490
    for x in j["items"]:
        assert x["department"] == "FOODS_2"


def test_risk_rankings_category_state_region_filters():
    r = client.get("/api/risk/rankings", params={"risk_type": "stockout", "category": "FOODS", "state": "TX", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert j["pagination"]["total"] > 0
    for x in j["items"]:
        assert x["category"] == "FOODS"
        assert x["state"] == "TX"


def test_risk_rankings_tier_and_pagination():
    r = client.get("/api/risk/rankings", params={"risk_type": "stockout", "tier": "Critical", "page": 2, "page_size": 10})
    assert r.status_code == 200
    j = r.json()
    assert j["pagination"]["page"] == 2
    assert j["pagination"]["page_size"] == 10
    assert len(j["items"]) == 10
    assert all(x["risk_tier"] == "Critical" for x in j["items"])


def test_risk_drivers_detail():
    r = client.get("/api/risk/drivers", params={"series": REAL_SERIES})
    assert r.status_code == 200
    j = r.json()
    assert j["series"]["product"] == "HOUSEHOLD_1_054"
    assert j["series"]["store"] == "WI_3"
    assert j["risk_rank"] is not None
    assert j["risk_tier"] in ("Low", "Medium", "High", "Critical")
    assert isinstance(j["components"], dict)
    assert j["provenance"] == "simulated"


def test_risk_drivers_requires_series():
    r = client.get("/api/risk/drivers")
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Provenance + undefined conventions
# --------------------------------------------------------------------------- #
def test_js_injects_simulated_chips_on_both_pages():
    assert 'provenanceChip("simulated")' in APP_JS


def test_js_renders_undefined_dash_for_deltas():
    assert '<span class="dash">—</span>' in APP_JS


# --------------------------------------------------------------------------- #
# Step-6 CSS locked palette + components
# --------------------------------------------------------------------------- #
def test_step6_css_uses_only_locked_palette():
    palette = {v.lower() for v in LOCKED_PALETTE.values()}
    allowed = palette | {"#c25a3a", "#8f3d2b"}  # documented danger family
    derived = {"#101513", "#1f2a26", "#b8bfb6", "#55605a"}
    for m in re.finditer(r"#([0-9a-fA-F]{6})\b", BASE_CSS):
        h = "#" + m.group(1).lower()
        if h in derived:
            continue
        assert h in allowed, f"off-palette hex in Step-6 CSS: {h}"


def test_step6_css_has_required_components():
    for sel in (".scen-row", ".scen-status", ".delta-up", ".delta-down",
                ".evidence", ".evidence__item", ".risk-row", ".tiercount"):
        assert sel in BASE_CSS, f"missing Step-6 component CSS {sel}"


# --------------------------------------------------------------------------- #
# Source-level data-layer enforcement
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_query_in_web_source():
    text = _source_text()
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text, re.IGNORECASE) is None


def test_no_full_daily_scan_v_units():
    assert "v_units" not in _source_text()


def test_risk_service_uses_correlated_dim_subqueries_only():
    risk_src = (WEB_SRC / "services" / "risk.py").read_text(encoding="utf-8")
    assert "EXISTS (SELECT 1 FROM dim_department" in risk_src
    assert "EXISTS (SELECT 1 FROM dim_category" in risk_src
    assert "st.state_id = %s" in risk_src


def test_risk_rankings_never_scans_fact_daily_sales():
    risk_src = (WEB_SRC / "services" / "risk.py").read_text(encoding="utf-8")
    assert "fact_daily_sales" not in risk_src
    assert "fact_scenario_result" in risk_src


# --------------------------------------------------------------------------- #
# Responsive layout presence (mobile-first grid via CSS classes already used)
# --------------------------------------------------------------------------- #
def test_responsive_layout_classes_present():
    assert "grid" in BASE_CSS  # existing responsive grid used by both pages