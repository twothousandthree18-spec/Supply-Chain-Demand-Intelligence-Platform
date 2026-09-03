"""
Phase 6 - Steps 1-2 validation harness (application shell + contracts + theme).

Covers the non-analytical build contracts delivered in this step:

  * ASGI app imports and exposes the expected route surface
  * the static shell renders at "/" with navigation for all 6 product areas
  * the locked 5-color theme tokens are present and exact
  * /api/health returns the locked reconciliation anchors + pilot + selected model
  * /api/meta returns the provenance contract, limitations, empty states, run map
  * /api/kpis/executive + contributions + signals return typed contracts
  * source-level enforcement: no fact_daily_sales / no full-daily v_units in src/web

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

LOCKED_PALETTE = {
    "Obsidian": "#090B0A",
    "Deep Jade": "#123C35",
    "Electric Jade": "#19E6B1",
    "Champagne": "#D8C39B",
    "Soft White": "#EDEFEA",
}

VIEWS = ["executive", "demand", "forecast", "inventory", "scenario", "risk"]


def _all_python_files():
    return list(WEB_SRC.rglob("*.py"))


def _source_text():
    parts = []
    for f in _all_python_files():
        parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# App / routes
# --------------------------------------------------------------------------- #
def test_app_imports_and_exposes_expected_routes():
    # FastAPI/Starlette include_router may keep routers as lazy _IncludedRouter
    # mounts rather than flattening sub-paths into app.routes, so collect the
    # flat set plus the original_router sub-paths under their /api group prefix,
    # then verify the light endpoints are actually reachable.
    flat = {getattr(r, "path", "") for r in app.routes}
    group = set()
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            sub = {getattr(gr, "path", "") for gr in (r.original_router.routes or [])}
            group.update("/api" + p for p in sub)
    paths = flat | group
    expected = [
        "/", "/static", "/api/health", "/api/meta",
        "/api/kpis/executive", "/api/kpis/contributions", "/api/executive/signals",
        "/api/docs", "/api/openapi.json",
    ]
    for e in expected:
        assert any(p == e or p.startswith(e) for p in paths), f"missing route {e}"
    # Health + meta are cheap enough to probe live; heavy endpoints are covered
    # under their own contract tests.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/meta").status_code == 200


# --------------------------------------------------------------------------- #
# Shell render + navigation
# --------------------------------------------------------------------------- #
def test_shell_renders_at_root():
    r = client.get("/")
    assert r.status_code == 200
    text = r.text
    assert "Supply Chain &amp; Demand Intelligence" in text
    assert "Supply Chain & Demand Intelligence Platform" in text


def test_navigation_lists_all_product_areas():
    r = client.get("/")
    html = r.text
    labels = {
        "executive": "Executive",
        "demand": "Demand",
        "forecast": "Forecast",
        "inventory": "Inventory",
        "scenario": "Scenario",
        "risk": "Operational Risk",
    }
    for view in VIEWS:
        assert f'data-view="{view}"' in html, f"nav missing view {view}"
        assert labels[view] in html, f"nav missing label for {view}"


def test_shell_links_theme_and_script():
    r = client.get("/")
    assert r.status_code == 200
    assert "/static/css/tokens.css" in r.text
    assert "/static/css/base.css" in r.text
    assert "/static/js/app.js" in r.text


# --------------------------------------------------------------------------- #
# Locked theme tokens
# --------------------------------------------------------------------------- #
def test_locked_palette_tokens_exact():
    css = (WEB_SRC / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    css_low = css.lower()
    for name, hexval in LOCKED_PALETTE.items():
        token = f"--color-{name.lower().replace(' ', '-')}"
        assert token in css, f"missing token {token}"
        assert hexval.lower() in css_low, f"palette color {name} {hexval} not present"


def test_no_off_palette_accent_introduced():
    # Enforce the locked 5-color family. The only allowed off-palette exception is
    # the documented danger-state family (--color-danger / --color-danger-muted),
    # needed to differentiate Critical/High risk severity; provenance/tier aliases
    # are derived from the palette. Every other --color-* must be from the palette.
    css = (WEB_SRC / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    palette = {v.lower() for v in LOCKED_PALETTE.values()}
    for m in re.finditer(r"--color-([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6});", css):
        token, h = m.group(1), m.group(2)
        # token == 'danger'/'danger-muted' is the documented off-palette exception
        if token == "danger" or token == "danger-muted":
            continue
        assert h.lower() in palette, f"off-palette color introduced for {token}: {h}"


def test_theme_matches_design_system_doc():
    # The palette in tokens.css must equal docs/design_system.md values.
    doc = (REPO_ROOT / "docs" / "design_system.md").read_text(encoding="utf-8")
    for name, hexval in LOCKED_PALETTE.items():
        assert hexval.lower() in doc.lower(), f"palette {name} not consistent with design system doc"


# --------------------------------------------------------------------------- #
# Health / metadata contracts (read-only)
# --------------------------------------------------------------------------- #
def test_health_returns_locked_anchors():
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["observed_units"] == 66_927_173
    assert j["forecast_final_grain"] == 853_720
    assert j["inventory_grain"] == 853_720
    assert j["scenario_result_rows"] == 213_430
    assert j["evaluation_rows"] == 122_088
    assert j["selected_model"] == "naive"
    assert j["ets_sarima_pilot_series"] == 64


def test_meta_contract():
    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    prov = j["provenance_contract"]
    assert prov["fact_inventory_simulation"] == "simulated"
    assert prov["fact_scenario_result"] == "simulated"
    assert prov["fact_forecast"] == "derived"
    assert prov["fact_demand_analysis"] == "derived"
    # empty state surfaced
    assert any("0" in s for s in j["empty_states"]) or any(
        "action_tradeoff" in s for s in j["empty_states"]
    )
    # limitation surfaced
    assert any("64" in s for s in j["limitations"])
    # 7 scenario runs
    assert len(j["scenario_run_map"]) == 7
    # comparison is an explicit empty state
    assert j["reconcile_anchors"]["comparison_rows"] == 0


# --------------------------------------------------------------------------- #
# Executive data contracts (typed, read-only)
# --------------------------------------------------------------------------- #
def test_executive_kpis_contract():
    r = client.get("/api/kpis/executive")
    assert r.status_code == 200
    j = r.json()
    h = j["headline"]
    assert h["revenue"]["provenance"] == "derived"
    assert h["units"]["value"] is not None
    assert h["units"]["provenance"] == "derived"
    assert "revenue_trend" in j and isinstance(j["revenue_trend"], list)


def test_executive_contributions_contract():
    r = client.get("/api/kpis/contributions")
    assert r.status_code == 200
    j = r.json()
    assert j["by_state"], "state contributions must be non-empty"
    for row in j["by_state"]:
        assert row["provenance"] == "derived"
        assert row["share_pct"] is not None
    assert all(row["rank"] == i + 1 for i, row in enumerate(j["by_state"]))


def test_executive_signals_provenance_simulated():
    r = client.get("/api/executive/signals")
    assert r.status_code == 200
    j = r.json()
    assert j["stockout_at_risk"] > 0 or j["excess_at_risk"] > 0
    for s in j["signals"]:
        assert s["provenance"] == "simulated"
        assert s["tier"] in {"High", "Critical"}


# --------------------------------------------------------------------------- #
# Source-level enforcement
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_query_in_web_source():
    # The word may appear only as provenance documentation (never as a queried table).
    text = _source_text()
    assert "FROM fact_daily_sales" not in text.upper().replace("FROM FACT_DAILY_SALES", "FROM fact_daily_sales")
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text, re.IGNORECASE) is None, (
        "data layer must not query fact_daily_sales"
    )


def test_no_full_daily_scan_v_units():
    # v_units is a ~59M-row view; it must not be aggregated for totals in src/web.
    text = _source_text()
    assert "v_units" not in text, "must not aggregate the daily v_units view"


def test_data_access_separated_from_presentation():
    # Only services modules import the DB helper; routers/static code must not.
    import_pattern = re.compile(r"from\s+(?:src\.)?etl\.db_utils\s+import|import\s+psycopg2")
    for f in _all_python_files():
        rel = (f.relative_to(REPO_ROOT)).as_posix()
        src = f.read_text(encoding="utf-8")
        if import_pattern.search(src):
            assert rel.startswith("src/web/services/") or rel == "src/web/settings.py", (
                f"DB access leaked outside services/settings: {rel}"
            )


def test_static_assets_exist():
    for rel in ["index.html", "css/tokens.css", "css/base.css", "js/app.js"]:
        assert (WEB_SRC / "static" / rel).exists(), f"missing static asset {rel}"