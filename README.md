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

Use this file to change source paths, output paths, Oracle connection details, and OLAP control settings.

## Pipelines

- `production_pipelines/01_oltp_load_pipeline.py`: Excel to `ARD_OPS_*` OLTP load with validation, stable IDs, and incremental history.
- `production_pipelines/02_oltp_to_olap_incremental_pipeline.py`: OLTP refresh followed by incremental OLAP procedure execution.
- `production_pipelines/03_audit_control_pipeline.py`: OLTP/OLAP counts, reconciliation, run control, and audit output.

## Safe Validation

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

## Full Run

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py
py .\production_pipelines\03_audit_control_pipeline.py
```

## Cron Run

```bash
cd "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project"
chmod +x production_pipelines/deploy/run_all_production_pipelines.sh
./production_pipelines/deploy/run_all_production_pipelines.sh
```

Example crontab:

```cron
0 2 * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

## Runtime Outputs

- `production_pipelines/logs/inc_pipeline.log`
- `production_pipelines/logs/inc_pipeline_manifest.jsonl`
- `production_pipelines/logs/etl_run_control.csv`
- `production_pipelines/errors/inc_pipeline_errors.csv`
- `production_pipelines/reconciliation/inc_pipeline_reconciliation.xlsx`
- `production_pipelines/history/incremental_history.xlsx`
- `production_pipelines/history/current_snapshot.json`

Full detailed documentation is available in:

```text
production_pipelines/END_TO_END_DOCUMENTATION.md
```
