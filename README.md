# Ardent Mills Production ETL

This repository contains the Ardent Mills Excel-to-Oracle ETL project. It keeps the original OLTP transformation package and adds production wrappers for incremental loading, OLAP refreshes, file archiving, database-backed audit and error tracking, logging, and email alerts.

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
ETL_AUDIT / ETL_ERROR / ETL_FILE_REGISTRY / ETL_LOAD_CONTROL tables, plus logs and email alerts
```

## Project Layout

```text
Ardent_mills/
|-- .env                         # Local secrets only, ignored by Git
|-- .env.example                 # Safe template for required environment variables
|-- requirements.txt             # Python dependencies
|-- README.md
|
|-- data/                        # Work queue: drop the new workbook here
|-- archive/                     # Timestamped copy of every file processed
|-- quarantine/                  # Files that failed processing
|-- samples/
|   |-- Ardent_Mills_Data.xlsx   # Reference copy of the source workbook
|
|-- sql/
|   |-- 01_tables.sql            # All sequences and tables (OLTP + OLAP + ETL control)
|   |-- 02_procedures.sql        # All incremental load procedures and wrappers
|
|-- ardent_mills_etl/            # OLTP ETL package (Excel -> ARD_OPS_* tables)
|   |-- main.py
|   |-- config/
|   |-- loaders/
|   |-- tests/
|   |-- transformers/
|   |-- utils/
|
|-- orchestration/
|   |-- run_all.py               # Single entry point: runs every stage in order
|
|-- production_pipelines/
|   |-- 01_oltp_load_pipeline.py
|   |-- 02_oltp_to_olap_incremental_pipeline.py
|   |-- pipeline_common.py
|   |-- config/                  # Optional pipeline_config.json, ignored by Git
|   |-- errors/                  # Generated at runtime
|   |-- history/
|   |-- logs/                    # Generated at runtime
|   |-- END_TO_END_DOCUMENTATION.md
```

## Key Components

- `ardent_mills_etl`: original OLTP ETL package. It reads Excel sheets, transforms data, validates relationships, and loads Oracle `ARD_OPS_*` tables with MERGE/upsert logic.
- `production_pipelines/01_oltp_load_pipeline.py`: production OLTP load wrapper. It runs Excel extraction, transformations, validation, Oracle load, per-table audit rows, and incremental history.
- `production_pipelines/02_oltp_to_olap_incremental_pipeline.py`: main end-to-end incremental pipeline. It can run the OLTP load and then execute OLAP incremental procedures for `DIM_*` and `FACT_*` tables.
- `orchestration/run_all.py`: single entry point. Runs each stage in dependency order and stops at the first failure.
- `production_pipelines/pipeline_common.py`: shared config loading, logging, paths, Oracle config, file intake and archiving, audit/error writing, and email alerting.

## Setup

Install Python dependencies:

```powershell
py -m pip install -r requirements.txt
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

Run everything end to end (the normal entry point):

```powershell
py orchestration\run_all.py
```

Useful variants:

```powershell
py orchestration\run_all.py --validate-only    # no database writes
py orchestration\run_all.py --only oltp        # a single stage
py orchestration\run_all.py -v                 # full log output
```

## Common Options

- `--excel <path>`: override the source workbook path.
- `--validate-only`: transform and validate without writing to Oracle.
- `--skip-connection-test`: skip the startup Oracle connection check.
- `--skip-oltp`: for pipeline `02`, skip the OLTP load step.
- `--skip-olap`: for pipeline `02`, skip OLAP procedure execution.
- `--load-date "YYYY-MM-DD HH:MM:SS"`: override the previous OLAP load date.

## Runtime Outputs

```text
production_pipelines/logs/inc_pipeline.log
production_pipelines/logs/inc_pipeline_manifest.jsonl
production_pipelines/errors/inc_pipeline_errors.csv
production_pipelines/history/incremental_history.xlsx
production_pipelines/history/current_snapshot.json
```

## Oracle Objects

The OLTP package loads `ARD_OPS_*` operational tables. The production OLAP pipeline then runs `RUN_INCREMENTAL_OLAP_LOAD` if it exists; otherwise it runs the individual incremental procedures listed in `pipeline_common.py`.

All Oracle objects are kept in two files, extracted from the live schema:

```text
sql/01_tables.sql        # 16 sequences + 38 tables (ARD_OPS_*, DIM_*/FACT_*, ETL_*)
sql/02_procedures.sql    # 16 INC_LOAD_* procedures + orchestration wrappers
```

Deploy a fresh schema by running them in order:

```powershell
sqlplus user/pass@dsn @sql/01_tables.sql
sqlplus user/pass@dsn @sql/02_procedures.sql
```

## Git And Security Notes

- `.env`, `production_pipelines/config/pipeline_config.json`, generated logs, histories, caches, and the `data/`, `archive/` and `quarantine/` working folders are ignored.
- Do not commit Oracle passwords, SMTP passwords, app passwords, or compiled `__pycache__` bytecode.
- If a credential was ever pushed, rotate it before using the repository in a shared remote.

Detailed operational documentation is available in:

```text
production_pipelines/END_TO_END_DOCUMENTATION.md
```

## Run History In The Database

Run history is recorded in Oracle rather than in local files, so it survives the
loss of any one working copy and is visible to everyone on the schema.

```text
ETL_AUDIT          one row per pipeline run: batch id, pipeline, row counts,
                   status, error message, start/finish, duration
ETL_ERROR          one row per failure: batch id, stage, error type, message,
                   full traceback
ETL_FILE_REGISTRY  one row per source file: name, SHA-256, archive path, status

`ETL_AUDIT` carries two kinds of row per run, joined by `BATCH_ID`: one summary
row for the run, and one row per target table holding the grain check that the
reconciliation workbook used to hold -- source rows in, rows landed, PASS/FAIL
and the reason. Comparing runs is now a query rather than opening two
spreadsheets.
ETL_LOAD_CONTROL   the incremental watermark the OLAP procedures read
```

Every run stamps a 32-character `BATCH_ID`, so a run's audit row and its error
rows join on that column. Audit writes are wrapped and never fail a load: if
history cannot be written the pipeline logs a warning and its own result stands.

## Source Files: Queue, Archive And Replay

`data/` is a work queue. It holds only files still waiting to be processed, and
a run leaves it empty.

```text
drop Ardent_Mills_Data.xlsx into data/
  -> hash it (SHA-256)
  -> already loaded with the same bytes?  -> log, skip, exit 0
  -> copy raw file to archive/YYYY/MM/DD/<name>_<timestamp>.xlsx
  -> register the file as IN_PROGRESS
  -> process the ARCHIVED copy, not the original
  -> success -> registry SUCCESS, original removed from data/
  -> failure -> registry FAILED,  original moved to quarantine/
```

The raw bytes are archived **before** anything parses them, because the archive
is the replay source: if the transformer crashes, what landed must still exist.
The original is only removed after the load succeeds, so a file is never in a
state where it exists nowhere.

The SHA-256 check is not about protecting the data -- every load is a MERGE and
is safe to repeat. It protects the *watermark*. Reloading identical bytes stamps
`UPDATED_DATE` on every row it touches, and `UPDATED_DATE` is exactly what the
`INC_LOAD_*` procedures filter on, so a redundant reload would push the whole
dataset back through the OLAP layer for nothing.

A failed file goes to `quarantine/` rather than staying in `data/`, where it
would fail every scheduled run forever and block the next good file behind it.

```powershell
py orchestration
un_all.py                 # process whatever is in data/
py production_pipelines_oltp_load_pipeline.py --force    # reload identical bytes
py production_pipelines_oltp_load_pipeline.py --excel path	o\other.xlsx
```

`--excel` bypasses the queue entirely: that file is neither archived nor removed,
because the caller owns it.
