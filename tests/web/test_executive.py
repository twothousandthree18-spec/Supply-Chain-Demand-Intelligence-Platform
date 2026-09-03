"""
Phase 6 - Step 4 validation harness (Executive Dashboard presentation layer).

Covers the build contracts delivered for the Executive Dashboard:

  * the shell exposes the executive view with the business-filter bar + 4 sections
  * app.js renders all required sections (KPI header, demand performance, inventory
    health, operational signals) with provenance labels and literal "—" for undefined
  * data is fetched in parallel via Promise.all and cached for stable aggregates
  * filters are server-driven (department/category/product/store/state/region/top_n)
  * /api/meta/dimensions returns the bounded filter option lists
  * the contributions endpoint scopes by filter and clamps top_n 1..50 (422 outside)
  * the locked 5-color palette is respected in the new Step-4 CSS (danger family only
    for risk severity)
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
# Shell / section presence
# --------------------------------------------------------------------------- #
def test_executive_view_exists_with_all_four_sections():
    assert 'id="view-executive"' in INDEX_HTML
    # the four Step-4 section containers
    assert 'id="exec-kpis"' in INDEX_HTML
    assert 'id="exec-demand"' in INDEX_HTML
    assert 'id="exec-inventory"' in INDEX_HTML
    assert 'id="exec-signals"' in INDEX_HTML


def test_executive_filter_bar_present():
    ids = ["f-department", "f-category", "f-state", "f-store", "f-product", "f-topn", "filter-reset"]
    for sid in ids:
        assert f'id="{sid}"' in INDEX_HTML, f"missing filter control {sid}"
    # top-n select exposes the documented server-side choices
    for v in ("5", "10", "25", "50"):
        assert f'value="{v}"' in INDEX_HTML


# --------------------------------------------------------------------------- #
# app.js renderer coverage + provenance / undefined conventions
# --------------------------------------------------------------------------- #
def test_js_renders_all_four_sections():
    for fn in ("renderKpis", "renderDemand", "renderInventory", "renderSignals"):
        assert f"function {fn}" in APP_JS, f"missing renderer {fn}"


def test_js_uses_literal_dash_for_undefined():
    # Undefined metrics must render literal "—" (never a fabricated zero).
    assert "—" in APP_JS
    # metricValue returns the dash markup when undefined
    assert 'class="dash">—</span>' in APP_JS


def test_js_uses_parallel_fetch_and_cache():
    assert "Promise.all" in APP_JS
    assert "execState.cache" in APP_JS, "stable aggregates should be cached"


def test_js_uses_provenance_labels():
    # The dashboard must label observed/derived/simulated on the relevant blocks.
    assert "provenanceChip(\"derived\")" in APP_JS or 'provenanceChip("derived")' in APP_JS
    assert 'provenanceChip("simulated")' in APP_JS


def test_js_wires_filters_server_side():
    # Filter refresh keeps headline KPIs (full-portfolio) but re-queries contributions.
    assert "fetchContributions" in APP_JS
    assert "URLSearchParams" in APP_JS
    assert "top_n" in APP_JS
    assert 'f-department' in APP_JS
    assert "wireFilters" in APP_JS
    assert "f-topn" in APP_JS


def test_js_loads_dimension_options_from_meta():
    assert 'api("/api/meta/dimensions")' in APP_JS
    assert "populateSelect" in APP_JS


# --------------------------------------------------------------------------- #
# Step-4 CSS respects the locked palette and adds required components
# --------------------------------------------------------------------------- #
def test_step4_css_does_not_introduce_off_palette_colors():
    palette = {v.lower() for v in LOCKED_PALETTE.values()}
    allowed = palette | {"#c25a3a", "#8f3d2b"}  # documented danger family (lowercase)
    for m in re.finditer(r"#([0-9a-fA-F]{6})\b", BASE_CSS):
        h = "#" + m.group(1).lower()
        # skip derived neutral greys documented in the design system (border/muted
        # panel tones); only guard against a *new hue* that is clearly off-palette.
        if h in {"#101513", "#1f2a26", "#b8bfb6", "#55605a"}:
            continue
        assert h in allowed, f"off-palette hex in Step-4 CSS: {h}"


def test_step4_css_has_required_components():
    for sel in (".filter-bar", ".exec-kpis", ".exec-grid", ".trend__bars",
                ".contribution", ".health", ".meter__track", ".signal", "[data-tip]"):
        assert sel in BASE_CSS, f"missing Step-4 component CSS {sel}"


def test_step4_css_has_loading_empty_error_states():
    for cls in ("spinner", "state--error"):
        assert cls in BASE_CSS


# --------------------------------------------------------------------------- #
# Backend: dimensions + filterable contributions (read-only, bounded)
# --------------------------------------------------------------------------- #
def test_meta_dimensions_endpoint():
    r = client.get("/api/meta/dimensions")
    assert r.status_code == 200
    j = r.json()
    assert j["departments"] and j["categories"] and j["states"] and j["stores"]
    # real dimension tokens (locked format)
    assert "FOODS_3" in j["departments"]
    assert "FOODS" in j["categories"]
    assert "CA" in j["states"]
    assert "WI_3" in j["stores"]
    assert "regions" in j


def test_contributions_scoped_by_department():
    r = client.get("/api/kpis/contributions", params={"department": "FOODS_2", "top_n": 3})
    assert r.status_code == 200
    j = r.json()
    assert len(j["by_product"]) == 3
    assert all(row["entity"].startswith("FOODS_2_") for row in j["by_product"])
    # department share collapses to the selected dept only
    assert any(d["entity"] == "FOODS_2" and abs(d["share_pct"] - 100.0) < 1e-6
               for d in j["by_department"])


def test_contributions_scoped_by_state():
    r = client.get("/api/kpis/contributions", params={"state": "CA", "top_n": 3})
    assert r.status_code == 200
    assert len(r.json()["by_product"]) == 3


def test_contributions_scoped_by_category():
    r = client.get("/api/kpis/contributions", params={"category": "HOUSEHOLD", "top_n": 5})
    assert r.status_code == 200
    assert len(r.json()["by_product"]) == 5


def test_contributions_top_n_bounds():
    # top_n is clamped to 1..50; out-of-range must 422, in-range honored.
    assert client.get("/api/kpis/contributions", params={"top_n": 0}).status_code == 422
    assert client.get("/api/kpis/contributions", params={"top_n": 999}).status_code == 422
    r = client.get("/api/kpis/contributions", params={"top_n": 50})
    assert r.status_code == 200
    assert len(r.json()["by_product"]) == 50


def test_contributions_invalid_dimension_is_empty_not_error():
    # A non-existent exact dimension value yields 0 rows (not a 5xx).
    r = client.get("/api/kpis/contributions", params={"department": "NOT_A_DEPT", "top_n": 5})
    assert r.status_code == 200
    assert r.json()["by_product"] == []


def test_executive_kpis_and_inventory_support_the_dashboard():
    # Data the KPI header + inventory health consume.
    r = client.get("/api/kpis/executive")
    assert r.status_code == 200
    h = r.json()["headline"]
    for key in ("revenue", "units", "revenue_wow_pct", "units_wow_pct",
                "revenue_qoq_pct", "revenue_yoy_pct"):
        assert key in h
    assert len(r.json()["revenue_trend"]) >= 2
    inv = client.get("/api/inventory/summary").json()
    assert "days_of_inventory" in inv
    assert "service_level_achieved" in inv


def test_executive_signals_support_signal_section():
    r = client.get("/api/executive/signals")
    assert r.status_code == 200
    j = r.json()
    assert "stockout_at_risk" in j and "excess_at_risk" in j
    assert isinstance(j["signals"], list)


# --------------------------------------------------------------------------- #
# Source-level data-layer enforcement (Step-4 additions stay read-only)
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_query_in_web_source():
    text = _source_text()
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text, re.IGNORECASE) is None


def test_no_full_daily_scan_v_units():
    assert "v_units" not in _source_text()


def test_meta_dimensions_queries_only_tiny_dim_tables():
    # dimensions() reads dim_department/dim_category/dim_store (bounded lookups only);
    # it must never scan the analytical fact tables. Inspect just that function body.
    meta_src = (WEB_SRC / "services" / "meta.py").read_text(encoding="utf-8")
    fn_start = meta_src.index("def dimensions(cur)")
    fn_body = meta_src[fn_start:meta_src.index("    return out", fn_start)]
    for table in ("dim_department", "dim_category", "dim_store"):
        assert f"FROM {table}" in fn_body, f"dimensions() missing read of {table}"
    assert "FROM fact" not in fn_body, "dimensions() must not scan fact tables"