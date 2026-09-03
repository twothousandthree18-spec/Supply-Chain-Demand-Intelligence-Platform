"""
Phase 6 - Step 3 focused API/data tests.

Exercises the Core API / Data-Integration endpoints (demand, forecast,
inventory, scenario, risk) against the locked read-only warehouse. All requests
are GET/read-only. Executive endpoints (with their heavier first-load
aggregation) are covered separately in test_shell.py and are not repeated here.

Coverage: endpoint contracts, pagination, filtering, provenance, empty states,
undefined metrics, the 64-series ETS/SARIMA pilot caveat, scenario status +
explicit comparison empty state, risk ranking, invalid parameters, and source
enforcement (no fact_daily_sales reads).
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

# A real product × store series present in the warehouse (surrogate 1:1).
REAL_SERIES = "HOUSEHOLD_1_054:WI_3"
UNKNOWN_SERIES = "NOPE_X:ZZ_1"


def _all_python_files():
    return list(WEB_SRC.rglob("*.py"))


def _source_text():
    return "\n".join(f.read_text(encoding="utf-8") for f in _all_python_files())


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #
class TestDemand:
    def test_demand_contract_and_pagination(self):
        r = client.get("/api/analytics/demand?page_size=25")
        assert r.status_code == 200
        j = r.json()
        assert "pagination" in j and "items" in j
        assert j["pagination"]["page"] == 1
        assert j["pagination"]["page_size"] == 25
        assert j["pagination"]["total"] > 0
        assert len(j["items"]) == 25
        row = j["items"][0]
        for field in ("product", "store", "risk_category", "provenance"):
            assert field in row
        assert row["provenance"] in {"observed", "derived", "simulated"}

    def test_demand_pagination_page_size_cap(self):
        assert client.get("/api/analytics/demand?page_size=999").status_code == 422

    def test_demand_filter_by_risk_category(self):
        r = client.get("/api/analytics/demand?risk_category=Critical&page_size=50")
        j = r.json()
        assert j["pagination"]["total"] > 0
        assert all(item["risk_category"] == "Critical" for item in j["items"])

    def test_demand_filter_by_product(self):
        r = client.get("/api/analytics/demand?product=HOUSEHOLD_1_054&page_size=50")
        j = r.json()
        assert j["pagination"]["total"] > 0
        assert all(item["product"] == "HOUSEHOLD_1_054" for item in j["items"])

    def test_demand_undefined_growth_field(self):
        # growth_defined flag + nullable growth: contract never fabricates a zero.
        r = client.get("/api/analytics/demand?page_size=200")
        j = r.json()
        for item in j["items"]:
            if not item["growth_defined"]:
                assert item["demand_growth_rate"] is None

    def test_demand_sort_deterministic(self):
        r1 = client.get("/api/analytics/demand?page_size=10&sort=cv_desc")
        r2 = client.get("/api/analytics/demand?page_size=10&sort=cv_desc")
        assert r1.json()["items"] == r2.json()["items"]
        cvs = [i["cv"] for i in r1.json()["items"] if i["cv"] is not None]
        assert cvs == sorted(cvs, reverse=True)

    def test_demand_segments(self):
        r = client.get("/api/analytics/demand/segments")
        assert r.status_code == 200
        j = r.json()
        assert "matrix" in j and "risk_breaks" in j
        total = sum(m["count"] for m in j["matrix"])
        assert total > 0
        assert sum(b["count"] for b in j["risk_breaks"]) == total
        assert j["risk_category"] == "derived"

    def test_demand_seasonality_bounded(self):
        r = client.get(f"/api/analytics/demand/seasonality?series={REAL_SERIES}")
        assert r.status_code == 200
        j = r.json()
        assert len(j["monthly_indices"]) == 12
        assert j["series"]["product"] and j["series"]["store"]
        assert j["provenance"] == "derived"

    def test_demand_seasonality_requires_series(self):
        r = client.get("/api/analytics/demand/seasonality")
        assert r.status_code == 400

    def test_demand_dow_scopes(self):
        r = client.get("/api/analytics/demand/dow")
        assert r.status_code == 200
        assert r.json()["scope_type"] is not None
        all_scope = client.get("/api/analytics/demand/dow?scope_type=store")
        j = all_scope.json()
        assert j["scope_type"] == "store"
        assert len(j["points"]) > 0
        assert all(p["scope_type"] == "store" for p in j["points"])

    def test_demand_dow_invalid_scope(self):
        assert client.get("/api/analytics/demand/dow?scope_type=bogus").status_code == 422


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
class TestForecast:
    def test_accuracy_contract_and_pilot_caveat(self):
        r = client.get("/api/forecast/accuracy")
        assert r.status_code == 200
        j = r.json()
        assert len(j["rows"]) == 6
        assert j["selected_model"] == "naive"
        assert j["pilot_series"] == 64
        assert j["caveat"] is not None
        by_id = {row["model_id"]: row for row in j["rows"]}
        # Models 1-4 full support; models 5-6 pilot-limited.
        for mid in (1, 2, 3, 4):
            assert by_id[mid]["support_series"] == 30_490
            assert by_id[mid]["pilot_limited"] is False
        for mid in (5, 6):
            assert by_id[mid]["support_series"] == 64
            assert by_id[mid]["pilot_limited"] is True
        assert all(r["provenance"] == "derived" for r in j["rows"])

    def test_accuracy_undefined_flag(self):
        j = client.get("/api/forecast/accuracy").json()
        for row in j["rows"]:
            assert "undefined" in row
            if row["mae"] is None:
                assert row["undefined"] is True
            else:
                assert row["mae"] >= 0 and row["rmse"] is not None

    def test_models_registry(self):
        j = client.get("/api/forecast/models").json()
        assert j["model_count"] == 6
        assert j["pilot_series"] == 64
        assert j["limitation_note"] is not None
        names = [m["model_name"] for m in j["models"]]
        assert "naive" in names and "sarima" in names
        selected = [m for m in j["models"] if m["is_selected"]]
        assert selected and selected[0]["model_name"] == "naive"

    def test_forecast_series_bounded(self):
        r = client.get(f"/api/forecast/series?series={REAL_SERIES}")
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 28  # final forecast horizon
        assert len(j["points"]) == 28
        first = j["points"][0]
        assert {"forecast_value", "lower_bound", "upper_bound", "forecast_date"} <= set(first)
        assert first["provenance"] == "derived"

    def test_forecast_series_unknown_empty(self):
        r = client.get(f"/api/forecast/series?series={UNKNOWN_SERIES}")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_forecast_series_requires_param(self):
        assert client.get("/api/forecast/series").status_code == 400


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
class TestInventory:
    def test_summary_contract(self):
        r = client.get("/api/inventory/summary")
        assert r.status_code == 200
        j = r.json()
        assert j["provenance"] == "simulated"
        assert j["horizon_days"] == 28
        for field in ("on_hand", "on_order", "backorder", "inventory_position",
                      "days_of_inventory", "service_level_achieved", "fill_rate",
                      "safety_stock", "reorder_point"):
            assert field in j

    def test_summary_aggregates_positive(self):
        j = client.get("/api/inventory/summary").json()
        # Locked baseline: service level ~0.95; on-hand sum positive.
        assert j["on_hand"] is not None and j["on_hand"] > 0
        if j["service_level_achieved"] is not None:
            assert 0 <= j["service_level_achieved"] <= 1

    def test_policy(self):
        r = client.get("/api/inventory/policy")
        assert r.status_code == 200
        j = r.json()
        assert j["provenance"] == "simulated"
        assert j["policy_name"] == "baseline_service_95_pct"
        assert j["reorder_policy"] is not None
        assert j["service_level_target"] is not None

    def test_horizon_bounded(self):
        r = client.get(f"/api/inventory/horizon?series={REAL_SERIES}")
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 28
        assert len(j["days"]) == 28
        day = j["days"][0]
        assert {"day_id", "inventory_position", "on_hand", "on_order", "stockout"} <= set(day)
        assert day["provenance"] == "simulated"

    def test_horizon_unknown_empty(self):
        assert client.get(f"/api/inventory/horizon?series={UNKNOWN_SERIES}").json()["total"] == 0


# --------------------------------------------------------------------------- #
# Scenario
# --------------------------------------------------------------------------- #
class TestScenario:
    def test_runs(self):
        r = client.get("/api/scenario/runs")
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 7
        names = {run["scenario_name"] for run in j["runs"]}
        assert {"baseline", "stockout_risk_rank", "excess_risk_rank"} <= names
        assert all(run["provenance"] == "simulated" for run in j["runs"])
        assert all(run["status"] for run in j["runs"])

    def test_deltas_excludes_baseline(self):
        r = client.get("/api/scenario/deltas")
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 6
        assert all(d["name"] != "baseline" for d in j["deltas"])
        assert all(d["provenance"] == "simulated" for d in j["deltas"])
        assert all("delta_stockout_days" in d and "series_count" in d for d in j["deltas"])

    def test_comparison_explicit_empty_state(self):
        r = client.get("/api/scenario/comparison")
        assert r.status_code == 200
        j = r.json()
        assert j["present"] is False
        assert j["rows"] == 0
        assert "no action_tradeoff" in j["reason"]


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #
class TestRisk:
    def test_rankings_pagination_and_determinism(self):
        r1 = client.get("/api/risk/rankings?risk_type=stockout&page_size=10")
        r2 = client.get("/api/risk/rankings?risk_type=stockout&page_size=10")
        j = r1.json()
        assert r1.status_code == 200
        assert j["pagination"]["total"] == 30_490
        assert len(j["items"]) == 10
        assert [i["risk_rank"] for i in j["items"]] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert r1.json() == r2.json()  # deterministic
        assert all(i["provenance"] == "simulated" for i in j["items"])

    def test_rankings_evidence_and_driver(self):
        j = client.get("/api/risk/rankings?risk_type=stockout&page_size=5").json()
        for item in j["items"]:
            assert "risk_score" in item and "risk_tier" in item
            assert isinstance(item["evidence"], dict)
            # The risk_components evidence schema keys.
            if item["evidence"]:
                assert any(k in item["evidence"] for k in
                           ("urgency", "service_gap", "volume_rank", "stockout_prob",
                            "volatility_rank"))

    def test_rankings_tier_filter(self):
        j = client.get("/api/risk/rankings?risk_type=stockout&tier=Critical&page_size=50").json()
        assert j["pagination"]["total"] > 0
        assert all(i["risk_tier"] == "Critical" for i in j["items"])
        assert j["tier"] == "Critical"

    def test_rankings_both_types(self):
        for rt in ("stockout", "excess"):
            j = client.get(f"/api/risk/rankings?risk_type={rt}&page_size=1").json()
            assert j["pagination"]["total"] == 30_490
            assert j["risk_type"] == rt

    def test_rankings_invalid_risk_type(self):
        assert client.get("/api/risk/rankings?risk_type=wartime").status_code == 422

    def test_rankings_page_size_cap(self):
        assert client.get("/api/risk/rankings?risk_type=stockout&page_size=999").status_code == 422

    def test_drivers_evidence(self):
        r = client.get(f"/api/risk/drivers?series={REAL_SERIES}")
        assert r.status_code == 200
        j = r.json()
        assert j["provenance"] == "simulated"
        assert j["risk_tier"] is not None
        assert j["risk_rank"] is not None
        assert set(j["components"]) <= {
            "urgency", "service_gap", "volume_rank", "stockout_prob",
            "volatility_rank", "dominant"}

    def test_drivers_unknown_series(self):
        assert client.get(f"/api/risk/drivers?series={UNKNOWN_SERIES}").json()["components"] == {}


# --------------------------------------------------------------------------- #
# Cross-cutting / source enforcement
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_read_in_web_source():
    text = _source_text().upper()
    assert re.search(r"(from|join)\s+fact_daily_sales\b", text) is None


def test_new_services_select_only_materialized_surfaces():
    # The new services must not embed forecasting/inventory/scenario math; a
    # conservative guard: they may only issue SELECT statements (no DML/DDL).
    for f in (WEB_SRC / "services").glob("*.py"):
        src = f.read_text(encoding="utf-8").upper()
        for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM",
                          "CREATE TABLE", "CREATE INDEX", "REFRESH MATERIALIZED"):
            assert forbidden not in src, f"write statement in service {f.name}"


def test_series_endpoints_are_bounded_per_series():
    # Explicit horizon endpoints must yield at most the 28-day window.
    for path in (f"/api/forecast/series?series={REAL_SERIES}",
                 f"/api/inventory/horizon?series={REAL_SERIES}"):
        j = client.get(path).json()
        assert j["total"] <= 28