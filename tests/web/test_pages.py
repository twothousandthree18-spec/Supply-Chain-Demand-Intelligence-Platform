"""
Phase 6 - Step 5 validation harness (Demand / Forecast / Inventory pages).

Covers the build contracts delivered for the three product-area pages:

  * shell exposes the three views with their filter bars + section containers
  * app.js renders all required sections (demand, forecast, inventory) and wires
    server-side filters, pagination, and per-series drill-down
  * forecast correctness: ETS/SARIMA are surfaced as a 64-series pilot and are
    never implied to be evaluated on all 30,490 series (source + endpoint)
  * inventory correctness: all figures are labeled simulated, never observed
  * undefined metrics render literal "—"; provenance chips are shown
  * the demand endpoints support department/category/state/region drill-down
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
def test_three_views_exist_with_sections():
    assert 'id="view-demand"' in INDEX_HTML
    assert 'id="view-forecast"' in INDEX_HTML
    assert 'id="view-inventory"' in INDEX_HTML
    # Demand sections
    for sid in ("demand-summary", "demand-matrix", "demand-risk", "demand-table"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing demand section {sid}"
    # Forecast sections
    for sid in ("forecast-selection", "forecast-accuracy", "forecast-series-card"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing forecast section {sid}"
    # Inventory sections
    for sid in ("inventory-summary", "inventory-horizon", "inventory-policy"):
        assert f'id="{sid}"' in INDEX_HTML, f"missing inventory section {sid}"


def test_demand_filter_bar_present():
    ids = ["d-department", "d-category", "d-state", "d-store", "d-trend",
           "d-volatility", "d-volume", "d-risk", "d-product", "d-page-size", "d-reset"]
    for sid in ids:
        assert f'id="{sid}"' in INDEX_HTML, f"missing demand filter {sid}"


def test_nav_has_all_three_entries():
    for view in ("demand", "forecast", "inventory"):
        assert f'data-view="{view}"' in INDEX_HTML


# --------------------------------------------------------------------------- #
# app.js renderer + API endpoint usage
# --------------------------------------------------------------------------- #
def test_js_has_lookup_buttons_for_per_series_drill_down():
    # Series drill-down must be triggered only by explicit user action (bounded).
    assert 'id="fc-view-series"' in INDEX_HTML
    assert 'id="inv-view-series"' in INDEX_HTML
    assert 'api("/api/forecast/series' in APP_JS or 'api(`/api/forecast/series' in APP_JS
    assert 'api("/api/inventory/horizon' in APP_JS or 'api(`/api/inventory/horizon' in APP_JS


def test_demand_renderers_and_endpoints():
    for fn in ("renderMatrix", "renderRiskBreaks", "renderDemandTableHtml"):
        assert f"function {fn}" in APP_JS, f"missing demand renderer {fn}"
    # Correct endpoint usage
    assert "/api/analytics/demand/segments" in APP_JS
    assert "/api/analytics/demand?" in APP_JS or "/api/analytics/demand?" in APP_JS
    assert "/api/analytics/demand" in APP_JS


def test_forecast_renderers_and_endpoints():
    for fn in ("renderForecastModels", "renderForecastAccuracy", "renderForecastSeries"):
        assert f"function {fn}" in APP_JS, f"missing forecast renderer {fn}"
    assert "/api/forecast/accuracy" in APP_JS
    assert "/api/forecast/models" in APP_JS
    assert "/api/forecast/series" in APP_JS


def test_inventory_renderers_and_endpoints():
    for fn in ("renderInventorySummary", "renderInventoryPolicy", "renderInventoryHorizon"):
        assert f"function {fn}" in APP_JS, f"missing inventory renderer {fn}"
    assert "/api/inventory/summary" in APP_JS
    assert "/api/inventory/policy" in APP_JS
    assert "/api/inventory/horizon" in APP_JS


def test_js_uses_promise_all_for_parallel_forecast_and_inventory_loads():
    # Forecast model+accuracy and inventory summary+policy load in parallel.
    assert "Promise.all([api(\"/api/forecast/models\"), api(\"/api/forecast/accuracy\")])" in APP_JS
    assert "Promise.all([api(\"/api/inventory/summary\"), api(\"/api/inventory/policy\")])" in APP_JS


# --------------------------------------------------------------------------- #
# Undefined metrics render "—" + provenance chips
# --------------------------------------------------------------------------- #
def test_undefined_dash_used_across_pages():
    for ui in ('<span class="dash">—</span>', "numberInCell", "plainNum"):
        assert ui in APP_JS, f"undefined/— convention missing {ui}"


def test_provenance_labels_simulated_and_derived_on_pages():
    assert 'provenanceChip("simulated")' in APP_JS
    assert 'provenanceChip("derived")' in APP_JS
    # Inventory explicitly disclaims observed inventory.
    assert "Not observed inventory" in APP_JS


# --------------------------------------------------------------------------- #
# 64-series forecast-support caveat
# --------------------------------------------------------------------------- #
def test_forecast_pilot_caveat_surfaced_in_js():
    assert "64-series pilot" in APP_JS
    assert "30,490" in APP_JS
    assert "not" in APP_JS
    assert "pilot" in APP_JS.lower()


def test_accuracy_endpoint_marks_pilot_support_only():
    r = client.get("/api/forecast/accuracy")
    assert r.status_code == 200
    j = r.json()
    by_id = {row["model_id"]: row for row in j["rows"]}
    # Models 1-4 evaluated on all 30,490 series; 5-6 on the 64-series pilot only.
    for mid in (1, 2, 3, 4):
        assert by_id[mid]["support_series"] == 30490, f"model {mid} should be full support"
        assert by_id[mid]["pilot_limited"] is False
    for mid in (5, 6):
        assert by_id[mid]["support_series"] == 64, f"model {mid} must be the 64-series pilot"
        assert by_id[mid]["pilot_limited"] is True
    assert j["pilot_series"] == 64
    assert j["caveat"] and "64-series pilot" in j["caveat"]


def test_models_endpoint_marks_pilot_and_caveat():
    r = client.get("/api/forecast/models")
    j = r.json()
    assert j["pilot_series"] == 64
    assert j["limitation_note"] and "64-series pilot" in j["limitation_note"]
    for m in j["models"]:
        if m["model_id"] in (5, 6):
            assert m["pilot_limited"] is True
            assert m["support_series"] == 64


def test_forecast_series_is_bounded_per_series():
    r = client.get("/api/forecast/series", params={"series": "HOUSEHOLD_1_054:WI_3"})
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 28, "28-day final forecast is bounded"
    assert len(j["points"]) == 28


# --------------------------------------------------------------------------- #
# Inventory simulated provenance
# --------------------------------------------------------------------------- #
def test_inventory_endpoints_carry_simulated_provenance():
    s = client.get("/api/inventory/summary").json()
    assert s["provenance"] == "simulated"
    assert s["days_of_inventory"] is not None
    assert "service_level_achieved" in s
    hz = client.get("/api/inventory/horizon", params={"series": "HOUSEHOLD_1_054:WI_3"}).json()
    assert hz["total"] == 28
    for d in hz["days"]:
        assert d["provenance"] == "simulated"
    p = client.get("/api/inventory/policy").json()
    assert p["provenance"] == "simulated"


# --------------------------------------------------------------------------- #
# Demand dimension drill-down (server-side) + pagination
# --------------------------------------------------------------------------- #
def test_demand_rows_filter_by_department():
    r = client.get("/api/analytics/demand", params={"department": "FOODS_2", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert j["pagination"]["total"] > 0
    assert j["pagination"]["total"] < 30490, "department filter must bound results"
    assert len(j["items"]) == 5


def test_demand_rows_filter_by_category():
    r = client.get("/api/analytics/demand", params={"category": "HOUSEHOLD", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert 0 < j["pagination"]["total"] < 30490


def test_demand_rows_filter_by_state_and_volatility_and_trend():
    r = client.get("/api/analytics/demand", params={"state": "CA", "volatility_class": "High", "trend_direction": "increasing", "page_size": 5})
    assert r.status_code == 200
    j = r.json()
    assert j["pagination"]["total"] > 0


def test_demand_segments_scoped_by_filter():
    r = client.get("/api/analytics/demand/segments", params={"category": "FOODS"})
    assert r.status_code == 200
    j = r.json()
    assert j["matrix"], "matrix must be non-empty under FOODS"
    assert j["risk_breaks"]
    total = sum(b["count"] for b in j["risk_breaks"])
    assert 0 < total < 30490


def test_demand_rows_pagination_bounded():
    r = client.get("/api/analytics/demand", params={"page": 2, "page_size": 50})
    assert r.status_code == 200
    j = r.json()
    assert j["pagination"]["page"] == 2
    assert j["pagination"]["page_size"] == 50
    assert len(j["items"]) == 50


def test_demand_sort_tokens_valid():
    for token in ("cv_desc", "mean_daily_units", "risk"):
        r = client.get("/api/analytics/demand", params={"sort": token, "page_size": 5})
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Step-5 CSS locked palette + component presence
# --------------------------------------------------------------------------- #
def test_step5_css_does_not_add_off_palette_hues():
    palette = {v.lower() for v in LOCKED_PALETTE.values()}
    allowed = palette | {"#c25a3a", "#8f3d2b"}  # documented danger family
    derived = {"#101513", "#1f2a26", "#b8bfb6", "#55605a"}
    for m in re.finditer(r"#([0-9a-fA-F]{6})\b", BASE_CSS):
        h = "#" + m.group(1).lower()
        if h in derived:
            continue
        assert h in allowed, f"off-palette hex in Step-5 CSS: {h}"


def test_step5_css_has_required_components():
    for sel in (".matrix", ".model-grid", ".model-card", ".fc-bars", ".hz-bars",
                ".badge--pilot", ".metric--risk", ".caveat", ".dl"):
        assert sel in BASE_CSS, f"missing Step-5 component CSS {sel}"


# --------------------------------------------------------------------------- #
# Source-level data-layer enforcement
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_query_in_web_source():
    text = _source_text()
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text, re.IGNORECASE) is None


def test_no_full_daily_scan_v_units():
    assert "v_units" not in _source_text()


def test_demand_dimension_filters_use_bounded_subqueries():
    demand_src = (WEB_SRC / "services" / "demand.py").read_text(encoding="utf-8")
    assert "EXISTS (SELECT 1 FROM dim_department" in demand_src
    assert "EXISTS (SELECT 1 FROM dim_category" in demand_src
    assert "st.state_id = %s" in demand_src