# Ardent Mills Production ETL Pipelines

This project wraps the original packaged OLTP ETL and adds production-style orchestration for incremental loading, logging, reconciliation, history tracking, and cron scheduling.

Original OLTP package:

```text
Ardent mill etl pipline/Ardent mill etl pipline/ardent_mills_etl
```

Production wrappers:

```text
production_pipelines
```

## Current Flow

```text
Ardent_Mills_Data.xlsx
        |
        v
01_oltp_load_pipeline.py
        |
        v
ARD_OPS_* OLTP tables
        |
        v
02_oltp_to_olap_incremental_pipeline.py
        |
        v
DIM_* and FACT_* OLAP tables
        |
        v
03_audit_control_pipeline.py
        |
        v
logs, errors, manifests, reconciliation, run control
```

## Config

Main settings are stored in:

```text
production_pipelines/config/pipeline_config.json
```

Use this file to change:

- Source Excel path
- Original OLTP package path
- Log/error/reconciliation/history paths
- Oracle connection details
- OLAP control process name

Oracle values can also be overridden with environment variables:

```text
ARDENT_ORACLE_HOST
ARDENT_ORACLE_PORT
ARDENT_ORACLE_SERVICE
ARDENT_ORACLE_USER
ARDENT_ORACLE_PASSWORD
```

## Pipeline 1: OLTP Load

File:

```text
production_pipelines/01_oltp_load_pipeline.py
```

What it does:

- Reads the Excel workbook.
- Uses the original `ardent_mills_etl` transformers and Oracle MERGE loader.
- Validates source-to-target row grain.
- Checks foreign-key issues before loading.
- Loads `ARD_OPS_*` tables.
- Appends incremental INSERT/UPDATE history after a successful non-validation load.
- Keeps generated IDs stable using the latest snapshot. Customer legal-name edits such as `JERSEY FOODS` to `JERSEY FOODS LTD` update the existing customer ID instead of creating a new one.

Safe validation:

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

Full OLTP load:

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py
```

## Pipeline 2: OLTP-to-OLAP Incremental Load

File:

```text
production_pipelines/02_oltp_to_olap_incremental_pipeline.py
```

What it does:

- Reads the previous successful OLAP load timestamp from `ETL_LOAD_CONTROL`.
- Runs the OLTP load first unless `--skip-oltp` is passed.
- Runs `RUN_INCREMENTAL_OLAP_LOAD` if available.
- Otherwise runs individual `INC_LOAD_DIM_*` and `INC_LOAD_FACT_*` procedures.
- Updates `ETL_LOAD_CONTROL` only after successful OLAP completion.
- Writes reconciliation and manifest output.

Full incremental run:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py
```

If Pipeline 1 already ran in the same shell script:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py --skip-oltp
```

## Pipeline 3: Audit and Control

File:

```text
production_pipelines/03_audit_control_pipeline.py
```

What it does:

- Captures OLTP and OLAP row counts.
- Appends run-control status to `logs/etl_run_control.csv`.
- Appends reconciliation details to one workbook.
- Writes run status to the manifest.

Run:

```powershell
py .\production_pipelines\03_audit_control_pipeline.py
```

## Runtime Outputs

- `logs/inc_pipeline.log` appends logs from all runs.
- `logs/inc_pipeline_manifest.jsonl` appends one JSON record per pipeline run.
- `logs/etl_run_control.csv` appends audit/control status rows.
- `errors/inc_pipeline_errors.csv` appends pipeline errors.
- `reconciliation/inc_pipeline_reconciliation.xlsx` appends reconciliation output.
- `reconciliation/inc_validation_workbook.xlsx` stores the latest validation workbook.
- `reconciliation/inc_diagnostics.json` stores the latest diagnostics JSON.
- `history/incremental_history.xlsx` appends only incremental INSERT/UPDATE history.
- `history/current_snapshot.json` stores the latest comparison baseline.

If `incremental_history.xlsx` is open in Excel, the pipeline logs a warning and does not advance the snapshot, so the same changes can be captured on the next run.

## WSL/Cron Runner

Shell runner:

```text
production_pipelines/deploy/run_all_production_pipelines.sh
```

It runs:

```text
01_oltp_load_pipeline.py
02_oltp_to_olap_incremental_pipeline.py --skip-oltp
03_audit_control_pipeline.py
```

Run manually from WSL:

```bash
cd "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project"
chmod +x production_pipelines/deploy/run_all_production_pipelines.sh
./production_pipelines/deploy/run_all_production_pipelines.sh
```

Open crontab:

```bash
crontab -e
```

Run every day at 2:00 AM:

```cron
0 2 * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

Run every minute for testing:

```cron
* * * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

Check cron output:

```bash
tail -f "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log"
```

## Optional Oracle Control Tables

Run this once in Oracle if you want database-side run/error/reconciliation logging:

```text
production_pipelines/sql/control_audit_reconciliation_tables.sql
```
