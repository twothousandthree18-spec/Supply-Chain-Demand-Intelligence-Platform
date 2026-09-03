"""
Supply Chain & Demand Intelligence Platform
Phase 3 - Forecasting package.

Baseline models (naive, seasonal-naive, moving/weighted moving average) for
ALL product/store series; statistical models (ETS/Holt-Winters) at the
aggregate + top-tier level and ARIMA only on a bounded pilot subset.
Chronological-only validation; no leakage; results recorded in model_registry,
fact_forecast and fact_forecast_evaluation.
"""
