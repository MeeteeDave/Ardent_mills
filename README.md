# Ardent Mills Production ETL

This repository contains the Ardent Mills Excel-to-Oracle ETL project. It keeps the original OLTP transformation package and adds production wrappers for incremental loading, OLAP refreshes, reconciliation, audit/control outputs, logging, error tracking, scheduling, and email alerts.

## Architecture

```text
Ardent_Mills_Data.xlsx
        |
        v
Original OLTP package
        |
        v
ARD_OPS_* Oracle OLTP tables
        |
        v
Incremental OLAP stored procedures
        |
        v
DIM_* and FACT_* Oracle OLAP tables
        |
        v
Logs, errors, manifests, reconciliation, history, audit/control output, email alerts
```

## Project Layout

```text
Ardent Mills project/
|-- .env                         # Local secrets only, ignored by Git
|-- .env.example                 # Safe template for required environment variables
|-- Ardent_Mills_Data.xlsx       # Source workbook
|-- README.md
|
|-- Ardent mill etl pipline/
|   |-- Ardent mill etl pipline/
|       |-- ardent_mills_etl/
|           |-- main.py
|           |-- requirements.txt
|           |-- config/
|           |-- loaders/
|           |-- sql/
|           |-- tests/
|           |-- transformers/
|           |-- utils/
|
|-- production_pipelines/
|   |-- 01_oltp_load_pipeline.py
|   |-- 02_oltp_to_olap_incremental_pipeline.py
|   |-- 03_audit_control_pipeline.py
|   |-- pipeline_common.py
|   |-- config/
|   |-- deploy/
|   |-- errors/
|   |-- history/
|   |-- logs/
|   |-- reconciliation/
|   |-- sql/
|   |-- END_TO_END_DOCUMENTATION.md
```

## Key Components

- `Ardent mill etl pipline/Ardent mill etl pipline/ardent_mills_etl`: original OLTP ETL package. It reads Excel sheets, transforms data, validates relationships, and loads Oracle `ARD_OPS_*` tables with MERGE/upsert logic.
- `production_pipelines/01_oltp_load_pipeline.py`: production OLTP load wrapper. It runs Excel extraction, transformations, validation, Oracle load, row-count reconciliation, and incremental history.
- `production_pipelines/02_oltp_to_olap_incremental_pipeline.py`: main end-to-end incremental pipeline. It can run the OLTP load and then execute OLAP incremental procedures for `DIM_*` and `FACT_*` tables.
- `production_pipelines/03_audit_control_pipeline.py`: audit/control step. It writes database row-count reconciliation and control output.
- `production_pipelines/pipeline_common.py`: shared config loading, logging, paths, Oracle config, reconciliation helpers, manifest writing, and email alerting.

## Setup

Install Python dependencies from the original package:

```powershell
py -m pip install -r "Ardent mill etl pipline\Ardent mill etl pipline\ardent_mills_etl\requirements.txt"
```

Create local environment settings:

```powershell
Copy-Item .env.example .env
```

Fill `.env` with Oracle and SMTP values. Do not commit `.env`.

```text
ARDENT_ORACLE_HOST=
ARDENT_ORACLE_PORT=1521
ARDENT_ORACLE_SERVICE=orcl
ARDENT_ORACLE_USER=
ARDENT_ORACLE_PASSWORD=

ARDENT_OLTP_ORACLE_HOST=
ARDENT_OLTP_ORACLE_PORT=1521
ARDENT_OLTP_ORACLE_SERVICE=orcl
ARDENT_OLTP_ORACLE_USER=
ARDENT_OLTP_ORACLE_PASSWORD=

ARDENT_ALERT_ENABLE_EMAIL=false
ARDENT_ALERT_SMTP_SERVER=smtp.gmail.com
ARDENT_ALERT_SMTP_PORT=587
ARDENT_ALERT_SENDER_EMAIL=
ARDENT_ALERT_SENDER_PASSWORD=
ARDENT_ALERT_RECIPIENT_EMAILS=
```

The production wrappers load `.env` automatically from the repository root. The original OLTP package also reads the same `.env` through `config/settings.py`.

## Configuration

Runtime secrets must live in `.env`.

Optional path and OLAP control settings can be kept in:

```text
production_pipelines/config/pipeline_config.json
```

That file is ignored by Git because it can contain environment-specific paths and connection details. Environment variables take priority over values in that JSON file.

## Email Alerts

Production pipeline alerts are sent by `send_pipeline_alert` in `production_pipelines/pipeline_common.py`.

Alerts are sent on both success and failure for:

- `01_oltp_load_pipeline.py`
- `02_oltp_to_olap_incremental_pipeline.py`
- `03_audit_control_pipeline.py`

To enable alerts, set this in `.env`:

```text
ARDENT_ALERT_ENABLE_EMAIL=true
```

For Gmail, use an app password in `ARDENT_ALERT_SENDER_PASSWORD`. The helper logs a clear message if email is disabled, if SMTP settings are missing, or if SMTP delivery fails.

## Running The Pipelines

Safe validation only, with no Oracle writes:

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

Run the main incremental pipeline:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py
```

Run audit/control reconciliation:

```powershell
py .\production_pipelines\03_audit_control_pipeline.py
```

Run all production steps on Windows:

```powershell
.\production_pipelines\deploy\run_all_production_pipelines.ps1
```

Run all production steps in WSL/Linux:

```bash
cd "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project"
chmod +x production_pipelines/deploy/run_all_production_pipelines.sh
./production_pipelines/deploy/run_all_production_pipelines.sh
```

## Common Options

- `--excel <path>`: override the source workbook path.
- `--validate-only`: transform and validate without writing to Oracle.
- `--skip-connection-test`: skip the startup Oracle connection check.
- `--skip-oltp`: for pipeline `02`, skip the OLTP load step.
- `--skip-olap`: for pipeline `02`, skip OLAP procedure execution.
- `--load-date "YYYY-MM-DD HH:MM:SS"`: override the previous OLAP load date.
- `--skip-db-counts`: for pipeline `03`, skip database row-count checks.

## Runtime Outputs

```text
production_pipelines/logs/inc_pipeline.log
production_pipelines/logs/inc_pipeline_manifest.jsonl
production_pipelines/logs/etl_run_control.csv
production_pipelines/errors/inc_pipeline_errors.csv
production_pipelines/reconciliation/inc_pipeline_reconciliation.xlsx
production_pipelines/reconciliation/inc_validation_workbook.xlsx
production_pipelines/reconciliation/inc_diagnostics.json
production_pipelines/history/incremental_history.xlsx
production_pipelines/history/current_snapshot.json
```

## Oracle Objects

The OLTP package loads `ARD_OPS_*` operational tables. The production OLAP pipeline then runs `RUN_INCREMENTAL_OLAP_LOAD` if it exists; otherwise it runs the individual incremental procedures listed in `pipeline_common.py`.

The project expects Oracle control/audit support tables and OLAP procedures to exist. Supporting SQL is kept under:

```text
production_pipelines/sql/
Ardent mill etl pipline/Ardent mill etl pipline/ardent_mills_etl/sql/
```

## Git And Security Notes

- `.env`, `production_pipelines/config/pipeline_config.json`, generated logs, reconciliation files, histories, caches, and archived working files are ignored.
- Do not commit Oracle passwords, SMTP passwords, app passwords, or compiled `__pycache__` bytecode.
- If a credential was ever pushed, rotate it before using the repository in a shared remote.

Detailed operational documentation is available in:

```text
production_pipelines/END_TO_END_DOCUMENTATION.md
```
