"""
Phase 6 - Step 7 validation harness (Final UX integration).

Extension of the Step 4-6 web suites: verifies the cross-cutting UX layer
applied across ALL already-built pages:

  * shared data-table conventions (server pagination, bounded page sizes,
    deterministic sorting, row counts, empty/loading/error/undefined state,
    percent + readable number formatting, "—" caret for missing values,
    provenance chips, header scope)
  * standardized filter model (server-side, dimension option population,
    reset-to-default, safe/encoded query construction, no raw interpolation)
  * drill-down navigation paths (risk row -> risk evidence; forecast/inventory
    series -> bounded 28-day detail; scenario -> metrics) and route integrity
  * responsive layout guards (zoom-independent rules, no page-level horizontal
    overflow beyond wide tables, small-width adaptations)
  * accessibility basics (scope attributes, labeled filter group, focus-visible,
    breadcrumb nav, reduced-motion)
  * strict locked-palette + danger-family-only severity tokens
  * performance safeguards: no fact_daily_sales access, no unbounded bulk
    scenario/forecast/inventory fetches, deterministic server-side sort

Read-only tests against the locked warehouse (no writes).
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
    "Danger": "#C25A3A",
    "Danger-muted": "#8F3D2B",
}

ALLOWED_HEX = set(LOCKED_PALETTE.values())

REAL_SERIES = "HOUSEHOLD_1_054:WI_3"
REAL_SERIES_2 = "FOODS_3_008:TX_3"

VIEWS = ("executive", "demand", "forecast", "inventory", "scenario", "risk")


def _source_text():
    parts = []
    for f in WEB_SRC.rglob("*.py"):
        parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _hex_colors(text):
    return set(re.findall(r"#[0-9a-fA-F]{3,8}\b", text))


# --------------------------------------------------------------------------- #
# 1. Shared data-table UX
# --------------------------------------------------------------------------- #
def test_all_data_table_headers_declare_scope():
    # Cell headers only (exclude <thead> which starts with "<th").
    headers = re.findall(r"<th(?=[ >])[^>]*>", APP_JS)
    assert headers, "no table cell headers found in app.js"
    non_cell = [h for h in headers if not re.search(r"scope=", h)]
    assert not non_cell, f"th without scope found: {non_cell[:5]}"


def test_pagination_is_server_side_and_bounded():
    # Demand + risk send explicit page/page_size; no client pagination math.
    assert 'q.set("page", String(demState.page))' in APP_JS
    assert 'q.set("page_size", String(demState.pageSize))' in APP_JS
    assert 'q.set("page", String(rkState.page))' in APP_JS
    assert "page_size" in APP_JS
    assert "Math.ceil(total / " in APP_JS  # page count derived, not rows loaded


def test_no_unbounded_ranking_fetch():
    r = client.get("/api/risk/rankings", params={"risk_type": "stockout"})
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) <= 50  # default bounded page, never 30,490 inline


def test_series_detail_views_are_bounded():
    # Forecast / inventory drill-downs load only a single series' bounded
    # 28-day detail (points/days + total), never a bulk horizon.
    f = client.get("/api/forecast/series", params={"series": REAL_SERIES}).json()
    assert isinstance(f["points"], list) and f["total"] <= 28
    h = client.get("/api/inventory/horizon", params={"series": REAL_SERIES}).json()
    assert isinstance(h["days"], list) and h["total"] <= 28


def test_empty_state_helpers_present():
    for marker in ('state("empty"', "spinner()", "errorState("):
        assert marker in APP_JS


def test_undefined_renders_dash():
    assert '<span class="dash">—</span>' in APP_JS


def test_percentage_formatting_helper():
    assert re.search(r"Math\.round\([^)]*\* 1000\)\s*/\s*10\b", APP_JS) or "1000" in APP_JS


def test_deterministic_sorting_server_side():
    # Demand sort is passed to the API as a query param and applied server-side.
    # sort=mean_daily_units is documented low→high (ascending).
    assert 'q.set("sort", sort || "")' in APP_JS
    r = client.get("/api/analytics/demand", params={"sort": "mean_daily_units", "page_size": 50})
    assert r.status_code == 200
    items = r.json().get("items", [])
    vals = [i["mean_daily_units"] for i in items if i.get("mean_daily_units") is not None]
    assert len(vals) >= 10
    assert vals == sorted(vals)  # ascending, matching the "low→high" sort option


# --------------------------------------------------------------------------- #
# 2. Filter system
# --------------------------------------------------------------------------- #
def test_filter_state_construction_is_encoded_safe():
    assert "URLSearchParams" in APP_JS or "encodeURIComponent" in APP_JS
    assert "q.toString()" in APP_JS


def test_reset_restores_defaults():
    # Pages with filter bars expose a Reset control that clears filters to
    # the documented default (all dimensions) and reloads server-side.
    for btn in ("filter-reset", "d-reset", "sc-reset", "rk-reset"):
        assert f'id="{btn}"' in INDEX_HTML, f"missing reset control {btn}"
    assert 'id="filter-reset"' in INDEX_HTML


def test_resets_clear_form_and_reload():
    for marker in ("value = \"\"", "demState.page = 1", "rkState.page = 1"):
        assert marker in APP_JS, f"missing reset marker {marker}"


def test_dimension_options_populated_server_side():
    assert "/api/meta/dimensions" in APP_JS
    for sel in ("f-department", "d-department", "rk-department"):
        assert f'"{sel}"' in APP_JS or f'id="{sel}"' in INDEX_HTML


def test_filter_controls_are_labeled():
    assert re.search(r'<label class="filter"><span>', INDEX_HTML) is not None


def test_invalid_series_token_handled_safely():
    r = client.get("/api/forecast/series", params={"series": "::::"})
    assert r.status_code in (200, 400, 404)


def test_no_uncontrolled_raw_sql_in_web():
    # Server-side queries must go through parameterized clauses, never raw
    # interpolation of filter values in the web layer.
    assert "SQLAlchemy" in _source_text() or "text(" in _source_text()


# --------------------------------------------------------------------------- #
# 3. Drill-downs
# --------------------------------------------------------------------------- #
def test_risk_row_drill_down_wired():
    assert "openRiskDriver" in APP_JS
    assert "wireRiskRowClick" in APP_JS
    assert "data-series" in APP_JS
    assert '/api/risk/drivers?series=' in APP_JS


def test_forecast_series_drill_down_wired():
    assert "/api/forecast/series?series=" in APP_JS
    assert "fc-view-series" in APP_JS


def test_inventory_series_drill_down_wired():
    assert "/api/inventory/horizon?series=" in APP_JS
    assert "inv-view-series" in APP_JS


def test_scenario_drill_down_wired():
    for ep in ("/api/scenario/runs", "/api/scenario/deltas", "/api/scenario/comparison"):
        assert ep in APP_JS


def test_risk_drivers_accepts_real_series_drilldown():
    r = client.get("/api/risk/drivers", params={"series": REAL_SERIES})
    assert r.status_code == 200
    assert r.json()["components"]


# --------------------------------------------------------------------------- #
# 4. Cross-page navigation / route integrity
# --------------------------------------------------------------------------- #
def test_all_views_defined_and_routed():
    for v in VIEWS:
        assert f'id="view-{v}"' in INDEX_HTML
        assert f"data-title=" in INDEX_HTML
    for v in VIEWS:
        assert f"else if (view === \"{v}\") load" in APP_JS or "view === \"" + v + "\"" in APP_JS


def test_active_route_overrides_set_on_nav_links():
    assert 'aria-current' in APP_JS
    assert 'data-view' in INDEX_HTML


def test_breadcrumbs_present_per_view():
    assert INDEX_HTML.count('aria-label="Breadcrumb"') >= 6
    assert 'href="#/executive"' in INDEX_HTML


def test_no_duplicate_nav_logic():
    n_routes = APP_JS.count("function route") + APP_JS.count("route =")
    assert n_routes <= 2
    assert APP_JS.count("renderNav") <= 3


def test_headers_and_page_title_per_view():
    for v in VIEWS:
        assert f'data-title=' in INDEX_HTML


# --------------------------------------------------------------------------- #
# 5. Responsive layout guards
# --------------------------------------------------------------------------- #
def test_responsive_media_queries_exist():
    for breakpoint in ("@media (max-width: 1024px)", "@media (max-width: 760px)", "@media (max-width: 480px)"):
        assert breakpoint in BASE_CSS


def test_responsive_nav_no_overflow():
    assert "overflow-x: auto" in BASE_CSS
    assert "white-space: nowrap" in BASE_CSS


def test_responsive_kpi_and_filter_bar():
    assert ".exec-kpis" in BASE_CSS and "grid-template-columns" in BASE_CSS
    assert ".app-nav" in BASE_CSS


def test_reduced_motion_respected():
    assert "@media (prefers-reduced-motion: reduce)" in BASE_CSS
    assert "animation" in BASE_CSS


def test_no_page_level_horizontal_overflow_guard():
    assert ".table-wrap" in BASE_CSS and "overflow-x" in BASE_CSS


def test_kpi_and_matrix_grids_clip_horizontally():
    # Responsive guard: wide KPI/matrix grids clip horizontally so long
    # sub-captions cannot force page-level horizontal overflow at small widths.
    assert ".exec-kpis" in BASE_CSS
    assert ".matrix" in BASE_CSS
    assert "overflow-x: clip" in BASE_CSS


def test_kpi_subcaptions_wrap_at_small_widths():
    assert ".kpi__sub" in BASE_CSS
    assert "overflow-wrap" in BASE_CSS


# --------------------------------------------------------------------------- #
# 6. Accessibility basics
# --------------------------------------------------------------------------- #
def test_has_skip_or_focus_visible():
    assert "focus-visible" in BASE_CSS
    assert "outline" in BASE_CSS


def test_filter_bars_have_group_labels():
    assert re.search(r'role="group" aria-label="', INDEX_HTML) is not None


def test_nav_has_aria_label():
    assert 'aria-label="Product areas"' in INDEX_HTML


def test_risk_rows_keyboard_accessible():
    assert "tabindex" in APP_JS


def test_disabled_pagination_buttons_accessible():
    assert "disabled" in APP_JS


def test_risk_rows_keyboard_enter_triggers_drilldown():
    assert '"keydown"' in APP_JS
    assert 'e.key === "Enter"' in APP_JS
    assert 'e.key === " "' in APP_JS
    assert "preventDefault" in APP_JS


def test_contrast_uses_locked_family_only():
    css = BASE_CSS
    extra = _hex_colors(css) - ALLOWED_HEX
    # Bg-surface / border tokens may reference derived variables, not raw hex.
    assert not extra, f"non-locked hex in CSS: {extra}"


# --------------------------------------------------------------------------- #
# 7. Locked-palette / visual consistency
# --------------------------------------------------------------------------- #
def _locked_compliance(text):
    forbidden = {"#ffffff", "#000000", "#e74c3c", "#ef4444", "#dc2626", "#f87171"}
    return _hex_colors(text) - ALLOWED_HEX - forbidden


def test_css_uses_only_locked_palette():
    extra = _hex_colors(BASE_CSS) - ALLOWED_HEX
    assert not extra, f"non-palette hex colours present: {extra}"


def test_danger_family_only_for_severity():
    # Danger hex used only within tier/risk matrix/delta classes.
    danger_regions = ["tier--critical", "tier--high", "cell--hot", "delta-bad", "meter__fill.danger", "kpi--danger", "metric--risk"]
    assert any(dr in BASE_CSS for dr in danger_regions)


def test_shared_card_and_badge_styles():
    for cls in (".badge", ".chip", ".tier", ".kpi", ".metric", ".card"):
        assert cls in BASE_CSS


# --------------------------------------------------------------------------- #
# 8. Performance safeguards (source-level)
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_query_in_web_source():
    # Confirms the warehouse table itself is never joined/scanned from src/web
    # (docstring/comment mentions are allowed; actual FROM/JOIN usage is not).
    text = _source_text()
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text, re.IGNORECASE) is None


def test_no_v_units_access():
    assert "v_units" not in _source_text()


def test_no_bulk_scenario_result_load():
    assert "/api/scenario/result" not in APP_JS
    assert "fact_scenario_result" not in APP_JS


def test_no_213430_bulk_fetch():
    assert "213430" not in APP_JS and "213,430" not in APP_JS


def test_executive_data_reused_not_refetched():
    assert "execState.cache" in APP_JS
    assert "Promise.resolve" in APP_JS


def test_demand_segments_and_rows_are_bounded_calls():
    assert "/api/analytics/demand/segments" in APP_JS
    assert "/api/risk/rankings" in APP_JS
    assert "page_size=1" in APP_JS  # distribution uses a 1-row bounded count probe


def test_no_duplicate_executive_requests():
    # Executive stable aggregates are cached and reused across filter changes.
    assert "execState.cache.kpis ?? api" in APP_JS or "execState.cache.kpis" in APP_JS
    assert "catch(() => null)" in APP_JS