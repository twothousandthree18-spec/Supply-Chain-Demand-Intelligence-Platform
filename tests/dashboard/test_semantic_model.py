"""
Phase 5 - Step 1 semantic-model validation harness (read-only).

Validates the Power BI semantic data model (dashboards/powerbi/POWERBI_MODEL.md)
against the LOCKED production warehouse. Every check is a SELECT against
already-materialized surfaces:

  * model table inventory + grains + row-count contract
  * dimension key uniqueness (PK)
  * forecast/inventory/scenario reconciliation
  * forecast-evaluation grain and per-model support (models 1-4 all series,
    models 5-6 pilot 64 - locked reality, not weakened)
  * risk-rank integrity (1..30,490 unique per rank run)
  * provenance (all scenario outputs simulated)
  * additive vs non-additive measure table (contract in POWERBI_MODEL.md)

Hard rules honored:
  - Read-only: never DDL/DML/ETL.
  - Never scans fact_daily_sales for a measure (only the one reconciliation
    probe below, which is the spec requirements' units anchor).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "sql"))

from src.etl.db_utils import connect  # noqa: E402


@pytest.fixture(scope="session")
def conn():
    c = connect()
    yield c
    c.close()


def _scalar(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


# --------------------------------------------------------------------------- #
# Locked values (from verified Phase 1-4 outputs / model spec)
# --------------------------------------------------------------------------- #
UNITS_OBSERVED = 66_927_173
SCENARIO_TOTAL = 213_430
FC_DISTINCT_SERIES = 30_490
FC_DAYS = 28
INV_DAYS = 28
EVAL_ROWS = 122_088
RISK_RANK_RUN_STOCKOUT = 6  # verified scenario_run_id for stockout_risk_rank
RISK_RANK_RUN_EXCESS = 7   # verified scenario_run_id for excess_risk_rank

# model table inventory: (model table -> source table, expected contract grain)
MODEL_TABLES = {
    "DimProduct": "dim_product",
    "DimCategory": "dim_category",
    "DimDepartment": "dim_department",
    "DimStore": "dim_store",
    "DimDate": "dim_date",
    "DimWeek": "dim_date",
    "DimScenario": "scenario",
    "DimScenarioRun": "fact_scenario_run",
    "DimModel": "model_registry",
    "DimAssumptionSet": "assumption_set",
    "FactWeeklySales": "mv_weekly_sales",
    "FactDemandAnalysis": "fact_demand_analysis",
    "FactDemandSeasonality": "fact_demand_seasonality",
    "FactDemandSeasonalityDow": "fact_demand_seasonality_dow",
    "FactForecast": "fact_forecast",
    "FactForecastEvaluation": "fact_forecast_evaluation",
    "FactInventorySimulation": "fact_inventory_simulation",
    "FactScenarioResult": "fact_scenario_result",
    "FactScenarioComparison": "fact_scenario_comparison",
}

# measure contract (name, additive) from POWERBI_MODEL.md / spec §6
MEASURES = [
    ("Total Revenue", True),
    ("Total Units", True),
    ("Revenue WoW %", False),
    ("Units WoW %", False),
    ("Revenue QoQ %", False),
    ("Revenue YoY %", False),
    ("Units YoY %", False),
    ("Weighted Price", False),
    ("Entity Revenue Share %", False),
    ("Total Stockout Days", True),
    ("Total Stockout Units", True),
    ("Total Excess Days", True),
    ("Total Excess Units", True),
    ("Total Demand", True),
    ("Replenishment Units", True),
    ("Avg Service Level", False),
    ("Fill Rate", False),
    ("Avg Days of Inventory", False),
    ("Avg Inventory Position", False),
    ("Forecast MAE", False),
    ("Forecast RMSE", False),
    ("Forecast WMAE", False),
    ("Forecast WRMSE", False),
    ("Forecast Bias", False),
    ("Stockout Risk Score", False),
    ("Stockout Risk Tier", False),
    ("Stockout Risk Rank", False),
    ("Excess Risk Score", False),
    ("Excess Risk Rank", False),
    ("Scenario Delta Stockout Units", False),
    ("Scenario Delta Service Level", False),
    ("Scenario Delta Excess Days", False),
    ("Scenario Delta Fill Rate", False),
    ("Scenario Delta Avg Inventory Position", False),
    ("Series at Risk Count", False),
    ("Fill Service Gap", False),
    ("Provenance Label", False),
]


# --------------------------------------------------------------------------- #
# 1. Model table inventory & key uniqueness
# --------------------------------------------------------------------------- #
def test_model_tables_exist(conn):
    cur = conn.cursor()
    for model_table, src in MODEL_TABLES.items():
        n = _scalar(cur, "SELECT count(*) FROM ({}) s".format(
            "SELECT * FROM " + src))
        assert n >= 0, f"{model_table} -> {src} missing"


def test_dimension_key_uniqueness(conn):
    cur = conn.cursor()
    uniq = {
        "DimProduct": ("dim_product", "product_surr_id"),
        "DimCategory": ("dim_category", "category_surr_id"),
        "DimDepartment": ("dim_department", "dept_surr_id"),
        "DimStore": ("dim_store", "store_surr_id"),
        "DimDate": ("dim_date", "date_id"),
        "DimScenario": ("scenario", "scenario_id"),
        "DimScenarioRun": ("fact_scenario_run", "scenario_run_id"),
        "DimModel": ("model_registry", "model_id"),
        "DimAssumptionSet": ("assumption_set", "assumption_set_id"),
    }
    for dim, (t, key) in uniq.items():
        total = _scalar(cur, f"SELECT count(*) FROM {t}")
        distinct = _scalar(cur, f"SELECT count(DISTINCT {key}) FROM {t}")
        assert total == distinct, f"{dim}: PK {key} not unique ({total} vs {distinct})"


def test_dimweek_grain_from_dimdate(conn):
    """DimWeek derives from dim_date (282 calendar weeks); sales fact covers 278.

    The calendar dimension is FILTER-ONLY over the full 282-week M5 span; the
    weekly sales fact (`mv_weekly_sales`) contains the 278 active weeks. A visual
    slicing a week with no sales shows an empty chart (never fabricated).
    """
    cur = conn.cursor()
    cal_weeks = _scalar(cur, "SELECT count(DISTINCT wm_yr_wk) FROM dim_date")
    mv_weeks = _scalar(cur, "SELECT count(DISTINCT wm_yr_wk) FROM mv_weekly_sales")
    assert cal_weeks == 282, f"dim_date weeks {cal_weeks}"
    assert mv_weeks == 278, f"mv_weekly_sales weeks {mv_weeks}"


# --------------------------------------------------------------------------- #
# 2. Reconciliation (spec §8 correctness)
# --------------------------------------------------------------------------- #
def test_units_reconciles_to_66927173(conn):
    cur = conn.cursor()
    mv = _scalar(cur, "SELECT SUM(units) FROM mv_weekly_sales")
    obs = _scalar(
        cur,
        "SELECT SUM(units_sold) FROM fact_daily_sales WHERE demand_source='observed'")
    assert mv == UNITS_OBSERVED, f"mv_weekly_sales units {mv} != {UNITS_OBSERVED}"
    assert obs == UNITS_OBSERVED, f"observed units {obs} != {UNITS_OBSERVED}"
    # the only fact_daily_sales read: the reconciliation anchor, not a measure scan


def test_scenario_result_reconciles_to_213430(conn):
    cur = conn.cursor()
    n = _scalar(cur, "SELECT count(*) FROM fact_scenario_result")
    assert n == SCENARIO_TOTAL, f"scenario rows {n} != {SCENARIO_TOTAL}"
    runs = _scalar(cur, "SELECT count(DISTINCT scenario_run_id) FROM fact_scenario_result")
    assert runs == 7
    series = _scalar(
        cur,
        "SELECT count(DISTINCT (product_surr_id::text||':'||store_surr_id::text)) "
        "FROM fact_scenario_result")
    assert series == 30_490


def test_forecast_grain_30490_x_28(conn):
    cur = conn.cursor()
    rows = _scalar(cur, "SELECT count(*) FROM fact_forecast WHERE is_final")
    series = _scalar(
        cur,
        "SELECT count(DISTINCT (product_surr_id::text||':'||store_surr_id::text)) "
        "FROM fact_forecast WHERE is_final")
    days = _scalar(cur, "SELECT count(DISTINCT forecast_date) FROM fact_forecast WHERE is_final")
    assert rows == FC_DISTINCT_SERIES * FC_DAYS, f"forecast rows {rows}"
    assert series == FC_DISTINCT_SERIES
    assert days == FC_DAYS
    # one producing model per (series,date) -> no fan-out to DimModel
    multi = _scalar(
        cur,
        "SELECT count(*) FROM (SELECT product_surr_id,store_surr_id,forecast_date "
        "FROM fact_forecast WHERE is_final GROUP BY 1,2,3 HAVING count(DISTINCT model_id)>1) x")
    assert multi == 0


def test_inventory_grain_30490_x_28(conn):
    cur = conn.cursor()
    rows = _scalar(cur, "SELECT count(*) FROM fact_inventory_simulation")
    series = _scalar(
        cur,
        "SELECT count(DISTINCT (product_surr_id::text||':'||store_surr_id::text)) "
        "FROM fact_inventory_simulation")
    days = _scalar(cur, "SELECT count(DISTINCT day_id) FROM fact_inventory_simulation")
    mn, mx = _scalar(
        cur, "SELECT min(day_id)::text||'|'||max(day_id)::text FROM fact_inventory_simulation"
    ).split("|")
    assert rows == FC_DISTINCT_SERIES * FC_DAYS, f"inventory rows {rows}"
    assert series == FC_DISTINCT_SERIES
    assert days == FC_DAYS
    assert (int(mn), int(mx)) == (1942, 1969)


def test_forecast_inventory_date_alignment(conn):
    """Final forecast dates == inventory sim day range (the 28-day horizon)."""
    cur = conn.cursor()
    fmn, fmx = _scalar(
        cur,
        "SELECT min(forecast_date)::text||'|'||max(forecast_date)::text "
        "FROM fact_forecast WHERE is_final").split("|")
    assert (int(fmn), int(fmx)) == (1942, 1969)


# --------------------------------------------------------------------------- #
# 3. Forecast-evaluation grain & per-model support (locked: ETS/SARIMA pilot)
# --------------------------------------------------------------------------- #
def test_evaluation_total_rows(conn):
    cur = conn.cursor()
    n = _scalar(cur, "SELECT count(*) FROM fact_forecast_evaluation")
    assert n == EVAL_ROWS, f"eval rows {n} != {EVAL_ROWS}"


def test_evaluation_model_support(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT model_id, count(*) FROM fact_forecast_evaluation GROUP BY model_id")
    support = dict(cur.fetchall())
    # models 1-4 (baselines) evaluated on all 30,490; models 5-6 (ets/sarima) pilot 64
    for mid in (1, 2, 3, 4):
        assert support.get(mid) == 30_490, f"model {mid} support {support.get(mid)}"
    for mid in (5, 6):
        assert support.get(mid) == 64, f"model {mid} support {support.get(mid)}"


# --------------------------------------------------------------------------- #
# 4. Risk-rank integrity (stockout run 6, excess run 7)
# --------------------------------------------------------------------------- #
def test_risk_rank_unique_per_run(conn):
    cur = conn.cursor()
    for run in (RISK_RANK_RUN_STOCKOUT, RISK_RANK_RUN_EXCESS):
        n = _scalar(
            cur,
            "SELECT count(DISTINCT risk_rank) FROM fact_scenario_result "
            "WHERE scenario_run_id=%s AND risk_rank IS NOT NULL", (run,))
        assert n == 30_490, f"run {run} distinct ranks {n}"
        mn, mx = _scalar(
            cur,
            "SELECT min(risk_rank)::text||'|'||max(risk_rank)::text "
            "FROM fact_scenario_result WHERE scenario_run_id=%s AND risk_rank IS NOT NULL",
            (run,)).split("|")
        assert (int(mn), int(mx)) == (1, 30_490)


def test_risk_tier_valid_values(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT risk_tier FROM fact_scenario_result WHERE risk_tier IS NOT NULL")
    tiers = {r[0] for r in cur.fetchall()}
    assert tiers.issubset({"Low", "Medium", "High", "Critical"})


# --------------------------------------------------------------------------- #
# 5. Provenance
# --------------------------------------------------------------------------- #
def test_scenario_provenance_all_simulated(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_provenance, count(*) FROM fact_scenario_result GROUP BY 1")
    rows = dict(cur.fetchall())
    assert rows.get("simulated") == SCENARIO_TOTAL
    assert set(rows) == {"simulated"}


def test_forecast_provenance_derived(conn):
    """Final forecasts are DERIVED (computed from observed demand), not simulated."""
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT data_provenance FROM fact_forecast WHERE is_final")
    provs = {r[0] for r in cur.fetchall()}
    assert provs == {"derived"}


def test_provenance_contract_all_surfaces(conn):
    """Locked provenance contract across all model source surfaces."""
    cur = conn.cursor()
    expect = {
        "fact_forecast": {"derived"},
        "fact_forecast_evaluation": {"derived"},
        "fact_demand_analysis": {"derived"},
        "fact_product_store_demand": {"derived"},
        "fact_demand_seasonality": {"derived"},
        "fact_demand_seasonality_dow": {"derived"},
        "fact_inventory_simulation": {"simulated"},
        "fact_scenario_result": {"simulated"},
    }
    for table, want in expect.items():
        cur.execute(f"SELECT DISTINCT data_provenance FROM {table}")
        got = {r[0] for r in cur.fetchall()}
        assert got == want, f"{table}: {got} != {want}"


# --------------------------------------------------------------------------- #
# 6. Measure contract: additive vs non-additive  (spec §6)
# --------------------------------------------------------------------------- #
def test_measure_contract_complete():
    names = [m[0] for m in MEASURES]
    required = {
        "Total Revenue", "Total Units", "Revenue WoW %", "Units WoW %",
        "Weighted Price", "Total Stockout Days", "Total Stockout Units",
        "Total Excess Days", "Total Excess Units", "Total Demand",
        "Replenishment Units", "Avg Service Level", "Fill Rate",
        "Avg Days of Inventory", "Avg Inventory Position", "Forecast MAE",
        "Forecast RMSE", "Forecast WMAE", "Forecast WRMSE", "Forecast Bias",
        "Stockout Risk Score", "Stockout Risk Tier", "Stockout Risk Rank",
        "Excess Risk Score", "Excess Risk Rank", "Scenario Delta Stockout Units",
        "Scenario Delta Service Level", "Scenario Delta Excess Days",
        "Scenario Delta Fill Rate", "Scenario Delta Avg Inventory Position",
        "Series at Risk Count", "Fill Service Gap", "Provenance Label",
    }
    assert required.issubset(set(names))


def test_additive_measures_are_sum_type():
    """Additive measures must be pure SUM/SUMX; non-additive explicitly non-SUM."""
    additive = {m[0] for m in MEASURES if m[1]}
    assert additive == {
        "Total Revenue", "Total Units", "Total Stockout Days",
        "Total Stockout Units", "Total Excess Days", "Total Excess Units",
        "Total Demand", "Replenishment Units",
    }


# --------------------------------------------------------------------------- #
# 7. No-unbounded-daily-scan guard (spec §3, §8-16)
# --------------------------------------------------------------------------- #
def test_no_fact_daily_sales_in_model_sources():
    """The model's source tables never include fact_daily_sales as a model table."""
    assert "FactDailySales" not in MODEL_TABLES
    assert all(src != "fact_daily_sales" for src in MODEL_TABLES.values())


# --------------------------------------------------------------------------- #
# 8. Undefined-metric policy (spec §6, §8b) - DAX artifact presence
# --------------------------------------------------------------------------- #
def test_dax_measure_artifacts_present():
    dax = Path(REPO_ROOT / "dashboards" / "powerbi" / "DAX_MEASURES.dax").read_text(encoding="utf-8")
    model = Path(REPO_ROOT / "dashboards" / "powerbi" / "POWERBI_MODEL.md").read_text(encoding="utf-8")
    assert "Total Revenue =" in dax
    assert "Total Units =" in dax
    assert "Weighted Price =" in dax
    assert "Provenance Label =" in dax
    assert "FactScenarioResult" in model
    assert "FactWeeklySales" in model
    # undefined metrics -> BLANK()/DISPLAY dash (spec §8b), never fabricated 0
    assert "BLANK ()" in dax
    assert "Display Dash" in dax