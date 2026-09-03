-- ============================================================
-- Supply Chain & Demand Intelligence Platform
-- Phase 2 - UTILITIES (helper functions for the warehouse)
-- ============================================================

-- Reusable: run a data-quality check and record the result in
-- data_quality_results. Called by the Python ETL validation step.
CREATE OR REPLACE FUNCTION record_quality_check(
    p_run_id        INT,
    p_check_name    TEXT,
    p_table_name    TEXT,
    p_severity      TEXT,     -- error | warning | info
    p_status        TEXT,     -- pass | fail | warn
    p_metric_value  NUMERIC,
    p_details       TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO data_quality_results
        (run_id, check_name, table_name, severity, status, metric_value, details)
    VALUES
        (p_run_id, p_check_name, p_table_name, p_severity, p_status, p_metric_value, p_details);
END;
$$ LANGUAGE plpgsql;

-- Start an ETL run, returning its run_id.
CREATE OR REPLACE FUNCTION start_etl_run(p_pipeline TEXT)
RETURNS INT AS $$
DECLARE v_run_id INT;
BEGIN
    INSERT INTO etl_run_log (pipeline, status) VALUES (p_pipeline, 'running')
    RETURNING run_id INTO v_run_id;
    RETURN v_run_id;
END;
$$ LANGUAGE plpgsql;

-- Finish an ETL run.
CREATE OR REPLACE FUNCTION finish_etl_run(
    p_run_id INT, p_status TEXT,
    p_records_processed BIGINT, p_records_loaded BIGINT, p_error TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE etl_run_log
    SET finished_at = now(), status = p_status,
        records_processed = p_records_processed,
        records_loaded = p_records_loaded,
        error_message = p_error
    WHERE run_id = p_run_id;
END;
$$ LANGUAGE plpgsql;
