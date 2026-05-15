-- Run once in Oracle if you want database-side pipeline observability.
-- The Python scripts already write file-based logs/errors/reconciliation.

CREATE TABLE ETL_RUN_LOG (
    run_id              VARCHAR2(40)   NOT NULL,
    pipeline_name       VARCHAR2(100)  NOT NULL,
    status              VARCHAR2(30)   NOT NULL,
    start_time          DATE           DEFAULT SYSDATE,
    end_time            DATE,
    source_file         VARCHAR2(1000),
    reconciliation_file VARCHAR2(1000),
    log_file            VARCHAR2(1000),
    created_date        DATE           DEFAULT SYSDATE,
    CONSTRAINT pk_etl_run_log PRIMARY KEY (run_id, pipeline_name)
);

CREATE TABLE ETL_ERROR_LOG (
    error_id        NUMBER GENERATED ALWAYS AS IDENTITY,
    run_id          VARCHAR2(40),
    pipeline_name   VARCHAR2(100),
    stage_name      VARCHAR2(100),
    error_type      VARCHAR2(200),
    error_message   CLOB,
    error_trace     CLOB,
    created_date    DATE DEFAULT SYSDATE,
    CONSTRAINT pk_etl_error_log PRIMARY KEY (error_id)
);

CREATE TABLE ETL_RECONCILIATION_LOG (
    reconciliation_id NUMBER GENERATED ALWAYS AS IDENTITY,
    run_id            VARCHAR2(40)  NOT NULL,
    pipeline_name     VARCHAR2(100) NOT NULL,
    layer_name        VARCHAR2(50),
    object_name       VARCHAR2(200),
    source_rows       NUMBER,
    transformed_rows  NUMBER,
    database_rows     NUMBER,
    status            VARCHAR2(50),
    notes             VARCHAR2(2000),
    created_date      DATE DEFAULT SYSDATE,
    CONSTRAINT pk_etl_reconciliation_log PRIMARY KEY (reconciliation_id)
);

CREATE TABLE ETL_LOAD_CONTROL (
    process_name      VARCHAR2(100) NOT NULL,
    last_load_date    DATE,
    last_success_date DATE,
    status            VARCHAR2(30),
    updated_date      DATE DEFAULT SYSDATE,
    CONSTRAINT pk_etl_load_control PRIMARY KEY (process_name)
);
