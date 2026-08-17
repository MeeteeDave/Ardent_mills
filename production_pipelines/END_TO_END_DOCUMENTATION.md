# Ardent Mills ETL Pipeline - End-to-End Documentation

## 1. Project Overview

This project implements a production-style ETL pipeline for the Ardent Mills data warehouse.

The source data arrives as an Excel workbook dropped into `data/`. The pipeline archives it, transforms it into operational OLTP tables named `ARD_OPS_*`, then incrementally loads OLAP dimension and fact tables such as `DIM_CUSTOMER`, `DIM_PRODUCT` and `FACT_SALES`.

The project supports:

- File intake with archiving and a hashed file registry
- Initial and incremental OLTP loading
- Incremental OLTP-to-OLAP loading, all dimensions before all facts
- Run history, per-table grain checks and error detail held in Oracle
- Incremental history capture
- A single orchestration entry point

Run history lives in the database (`ETL_AUDIT`, `ETL_ERROR`, `ETL_FILE_REGISTRY`, `ETL_LOAD_CONTROL`), not in local spreadsheets. A file on one machine is invisible to everyone else and is lost with that machine.

## 2. High-Level Architecture

The pipeline follows this flow:

```text
Workbook dropped into data/
        |
        v
Hash check -> archive raw bytes -> register file
        |
        v
Original OLTP ETL Package  (reads the ARCHIVED copy)
        |
        v
ARD_OPS_* OLTP Tables
        |
        v
RUN_INCREMENTAL_OLAP_LOAD  (11 dimensions, then 5 facts)
        |
        v
DIM_* and FACT_* OLAP Tables
        |
        v
ETL_AUDIT / ETL_ERROR / ETL_FILE_REGISTRY / ETL_LOAD_CONTROL
```

The original OLTP package is kept as the source of truth:

```text
ardent_mills_etl
```

The production wrapper scripts are kept here:

```text
production_pipelines
```

The single entry point is:

```text
orchestration/run_all.py
```

## 3. Main Folder Structure


```text
Ardent_mills/
|
|-- data/                        # Work queue: drop the new workbook here
|-- archive/                     # Timestamped copy of every file processed
|-- quarantine/                  # Files that failed processing
|-- samples/
|   |-- Ardent_Mills_Data.xlsx   # Reference copy of the source workbook
|
|-- sql/
|   |-- 01_tables.sql            # Sequences and all tables
|   |-- 02_procedures.sql        # All INC_LOAD_* procedures and the wrapper
|
|-- ardent_mills_etl/
|   |-- transformers/
|   |-- loaders/
|   |-- utils/
|   |-- config/
|   |-- tests/
|
|-- orchestration/
|   |-- run_all.py               # Single entry point
|
|-- production_pipelines/
|   |-- 01_oltp_load_pipeline.py
|   |-- 02_oltp_to_olap_incremental_pipeline.py
|   |-- pipeline_common.py
|   |-- config/
|   |   |-- pipeline_config.json
|   |-- logs/
|   |-- errors/
|   |-- history/
|   |-- END_TO_END_DOCUMENTATION.md
```

## 4. Configuration File


The main config file is:

```text
production_pipelines/config/pipeline_config.json
```

This file stores project settings such as:

- Data, archive and quarantine folder paths
- OLTP package path
- Log file path
- Error file path
- History file path
- Oracle host, port, service name, username, and password
- OLAP control process name

This keeps environment-specific values outside the Python logic.

Oracle values can also be overridden using environment variables:

```text
ARDENT_ORACLE_HOST
ARDENT_ORACLE_PORT
ARDENT_ORACLE_SERVICE
ARDENT_ORACLE_USER
ARDENT_ORACLE_PASSWORD
```

## 5. Pipeline 1: OLTP Load Pipeline


File:

```text
production_pipelines/01_oltp_load_pipeline.py
```

Purpose:

This pipeline reads the Excel source file, applies the original OLTP transformations, validates the transformed data, and loads the `ARD_OPS_*` Oracle tables.

Main activities:

1. Discovers the workbook waiting in `data/`, hashes it, archives the raw bytes, and registers it (see section 14).
2. Calls the original packaged transformer functions against the archived copy.
3. Builds OLTP tables such as:
   - `ARD_OPS_SITE`
   - `ARD_OPS_PRODUCT`
   - `ARD_OPS_CUSTOMER`
   - `ARD_OPS_SALESORDER`
   - `ARD_OPS_SALESORDERLINE`
   - `ARD_OPS_PACKRUN`
   - `ARD_OPS_MILLRUN`
   - `ARD_OPS_WORKORDER`
   - `ARD_OPS_BINCLEANINGLOG`
   - `ARD_OPS_FILLORDER`
4. Runs validation and foreign-key checks.
5. Loads Oracle using MERGE/upsert logic.
6. Writes a run summary row and one per-table grain row to `ETL_AUDIT`.
7. Updates incremental history after successful database load.
8. Clears the processed file from `data/`, or quarantines it on failure.

Safe validation command:

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

Full OLTP load command:

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py
```

## 6. Pipeline 2: OLTP-to-OLAP Incremental Pipeline


File:

```text
production_pipelines/02_oltp_to_olap_incremental_pipeline.py
```

Purpose:

This is the main incremental pipeline. It first runs the OLTP load, then runs OLAP incremental procedures to move changed data from `ARD_OPS_*` tables into `DIM_*` and `FACT_*` tables.

Main activities:

1. Reads the previous successful OLAP load date from `ETL_LOAD_CONTROL`.
2. Runs the original packaged OLTP transformation/load step.
3. Loads new or changed rows into `ARD_OPS_*`.
4. Runs `RUN_INCREMENTAL_OLAP_LOAD`, which calls all 16 procedures in order.
5. Updates `ETL_LOAD_CONTROL` only after successful completion.
6. Writes logs, manifest, audit rows, and history.

OLAP procedure order, enforced inside `RUN_INCREMENTAL_OLAP_LOAD`. Every dimension loads before any fact, because a fact resolves its foreign keys by looking the business key up in the dimension -- a fact built on a stale dimension drops or misassigns rows.

Dimensions first:

```text
INC_LOAD_DIM_DATE
INC_LOAD_DIM_SITE
INC_LOAD_DIM_PRODUCT
INC_LOAD_DIM_CUSTOMER
INC_LOAD_DIM_SHIPTO
INC_LOAD_DIM_CARRIER
INC_LOAD_DIM_PACKLINE
INC_LOAD_DIM_MAINTENANCE_TYPE
INC_LOAD_DIM_BIN
INC_LOAD_DIM_CLEANING_TYPE
INC_LOAD_DIM_PRODUCTION_MIX
```

Facts next:

```text
INC_LOAD_FACT_SALES
INC_LOAD_FACT_PACK_PRODUCTION
INC_LOAD_FACT_MILL_PRODUCTION
INC_LOAD_FACT_MAINTENANCE
INC_LOAD_FACT_BIN_CLEANING
```

Full incremental command:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py
```

Validation-only command:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py --validate-only
```

Skip OLTP and run only OLAP:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py --skip-oltp
```

Skip OLAP and run only OLTP:

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py --skip-olap
```

## 7. Orchestration: run_all.py

`orchestration/run_all.py` is the normal entry point. It runs the stages in dependency order and stops at the first failure, so the OLAP layer is never built on a half-loaded OLTP layer.

```text
Stage 1  OLTP   01_oltp_load_pipeline.py
Stage 2  OLAP   02_oltp_to_olap_incremental_pipeline.py --skip-oltp
```

Stage 2 is invoked with `--skip-oltp` because stage 1 has already loaded the workbook; without it the Excel load would run twice.

```powershell
py orchestration/run_all.py                     # process whatever is in data/
py orchestration/run_all.py --validate-only     # no database writes
py orchestration/run_all.py --only oltp         # a single stage
py orchestration/run_all.py --force             # reload identical bytes
py orchestration/run_all.py -v                  # full log output
```

Each stage prints one progress line with its outcome and duration. On failure the script prints the failing stage, the reason it could extract from the log, and how many stages did not run.

## 8. Logging


The project uses one common log file:

```text
production_pipelines/logs/inc_pipeline.log
```

Every pipeline run appends to the same file. This avoids creating a new log file for every run.

The log file records:

- Pipeline start time
- Run ID
- Source file being read
- Source sheet counts
- Validation summary
- Load status
- Batch id, archive path and audit row confirmations
- Errors, if any
- Pipeline completion status

## 9. Error Handling


All pipeline errors are written into one common error file:

```text
production_pipelines/errors/inc_pipeline_errors.csv
```

The error file contains:

- Run ID
- Pipeline name
- Failed stage
- Error type
- Error message
- Traceback
- Created timestamp

This helps identify which pipeline failed and why.

## 10. Audit, Error And Grain Checks

Run history is written to Oracle. There is no reconciliation workbook: an Excel file only ever existed on the machine that produced it, which is the failure mode this project already suffered once.

`ETL_AUDIT` carries two kinds of row per run, joined by `BATCH_ID`:

```text
run summary   one row: pipeline, total rows read/loaded, status, duration
per table     one row per target table: source sheet, rows in, rows landed,
              PASS/FAIL and the reason when it fails
```

The per-table rows are the grain checks the reconciliation workbook used to hold. A collapse such as `ARD_OPS_SalesOrder read=1614 loaded=1329` is expected and explained in the row itself: SalesOrder is a header table, so multiple lines sharing an `ORDER_NO` become one header.

`ETL_ERROR` holds one row per failure with the batch id, stage, error type, message and full traceback.

Every audit write is wrapped. A failure to record history logs a warning and is swallowed, so the pipeline result always stands on its own.

```sql
-- compare the last two runs of a pipeline
SELECT BATCH_ID, TARGET_TABLE, ROWS_READ, ROWS_LOADED, STATUS
  FROM ETL_AUDIT
 WHERE PIPELINE_NAME = '01_oltp_load'
 ORDER BY AUDIT_ID DESC;

-- anything that failed, with its error
SELECT a.BATCH_ID, a.TARGET_TABLE, a.ERROR_MESSAGE, e.ERROR_TYPE
  FROM ETL_AUDIT a
  LEFT JOIN ETL_ERROR e ON e.BATCH_ID = a.BATCH_ID
 WHERE a.STATUS = 'FAILED'
 ORDER BY a.AUDIT_ID DESC;
```

## 11. Incremental History


The incremental history workbook is:

```text
production_pipelines/history/incremental_history.xlsx
```

This file stores only detected `INSERT` and `UPDATE` changes from incremental runs.

The current comparison baseline is:

```text
production_pipelines/history/current_snapshot.json
```

How it works:

1. The pipeline compares the newly transformed tables with the previous snapshot.
2. If a row is new, it is marked as `INSERT`.
3. If an existing row changed, it is marked as `UPDATE`.
4. Only inserts and updates are appended to `incremental_history.xlsx`.
5. The latest full transformed state is saved into `current_snapshot.json`.

This avoids creating a new history Excel file for every run.

## 12. ID Stability Fix


Earlier, some IDs were generated based on row position. That caused a problem:

If a new customer was added above existing customers alphabetically, existing customer IDs could shift.

Example problem:

```text
ORLANDO FOODS INC had customer_id 3069
New customer JERSEY FOODS was added
customer_id 3069 could incorrectly point to JERSEY FOODS
```

This has been fixed.

Now generated IDs are preserved from the previous snapshot using business keys.

Examples:

```text
Customer ID is preserved by customer name.
Sales order ID is preserved by order number.
Product ID is preserved by product code.
Pack run ID is preserved by pack run business columns.
```

The validation check confirmed:

```text
shifted_ids = 0
```

for all generated-ID tables.

## 13. Run Manifest


The manifest file is:

```text
production_pipelines/logs/inc_pipeline_manifest.jsonl
```

It stores one JSON record per pipeline run.

It includes:

- Pipeline name
- Run ID
- Created timestamp
- Status
- Excel path
- Reconciliation path
- Validation mode
- Error file path if failed

This is useful for auditing and troubleshooting.

## 14. File Intake, Archive And Registry

`data/` is a work queue. It holds only files still waiting to be processed, and a run leaves it empty.

```text
drop the workbook into data/
  -> SHA-256 it
  -> identical bytes already loaded?  -> log, skip, exit 0
  -> copy the RAW file to archive/YYYY/MM/DD/<name>_<timestamp>.xlsx
  -> register it IN_PROGRESS in ETL_FILE_REGISTRY
  -> process the ARCHIVED copy, not the original
  -> success -> registry SUCCESS, original removed from data/
  -> failure -> registry FAILED,  original moved to quarantine/
```

The raw bytes are archived **before** anything parses them, because the archive is the replay source: if the transformer crashes, what landed must still exist. The original is removed only after the load succeeds, so the file is never in a state where it exists nowhere.

The SHA-256 check protects the *watermark*, not the data. Every load is a MERGE and is safe to repeat, but reloading identical bytes stamps `UPDATED_DATE` on every row it touches, and `UPDATED_DATE` is exactly what the `INC_LOAD_*` procedures filter on. A redundant reload would therefore push the whole dataset back through the OLAP layer for nothing. `--force` overrides the skip when you genuinely want to reload.

A file that fails processing moves to `quarantine/` rather than staying in `data/`, where it would fail every scheduled run forever and block the next good file behind it.

Only *data* failures quarantine the file. A failure that looks like infrastructure -- `DPY-6005`, `ORA-12541`, a TNS or timeout error -- leaves the file in `data/` for the next run to retry, because the file is fine and the database was not. Quarantining on a network blip would silently empty the queue, and every later run would report "nothing to process" while looking perfectly healthy.

An empty queue is success, not failure: a scheduled run with nothing to do logs and exits 0.

`--excel <path>` bypasses the queue entirely. That file is neither archived nor removed, because the caller owns it.

## 15. Deployment And Scheduling

Schedule the single entry point. It already runs the stages in order and stops at the first failure.

Windows Task Scheduler:

```powershell
py "C:/projects/Ardent mills/orchestration/run_all.py"
```

Linux cron, daily at 02:00:

```bash
0 2 * * * cd /path/to/Ardent_mills && python orchestration/run_all.py >> /var/log/ardent_etl.log 2>&1
```

Because an empty `data/` folder exits 0, a schedule can run as often as you like: runs with no new file are cheap and silent. Drop a workbook into `data/` and the next scheduled run picks it up.

Set `ARDENT_ALERT_ENABLE_EMAIL=true` in `.env` to have each run email its result.

## 16. How to Test the Pipeline


### Step 1: Validate transformations only

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

Expected result:

- No Oracle load, and no audit rows written
- Validation summary printed, all 18 target tables PASS
- The workbook is read in place: not archived, not removed from `data/`
- Log file updated

### Step 2: Test OLTP load

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py
```

Expected result:

- `ARD_OPS_*` tables loaded
- Row counts available
- Incremental history updated if changes exist

### Step 3: Test OLTP-to-OLAP incremental load

```powershell
py .\production_pipelines\02_oltp_to_olap_incremental_pipeline.py
```

Expected result:

- OLTP tables loaded first
- OLAP procedures executed
- `DIM_*` and `FACT_*` tables updated
- `ETL_LOAD_CONTROL` updated after success

### Step 4: Test the full run through the orchestrator

```powershell
py orchestration/run_all.py
```

Expected result:

- Both stages report `ok` with a duration
- The workbook is archived and removed from `data/`
- `ETL_AUDIT` gains a run summary row plus one row per target table

### Step 5: Test the intake guards

```powershell
py orchestration/run_all.py                 # empty data/ -> exits 0, nothing to do
py orchestration/run_all.py                 # same file again -> skipped by hash
py orchestration/run_all.py --force         # reloads it anyway
```

Expected result:

- An empty queue is a success, not a failure
- Identical bytes are skipped with a message naming the earlier archive
- `--force` reloads and writes a fresh `ETL_FILE_REGISTRY` row

Verify in Oracle:

```sql
SELECT FILE_NAME, SUBSTR(FILE_HASH,1,12), STATUS, ARCHIVE_PATH
  FROM ETL_FILE_REGISTRY ORDER BY FILE_ID DESC;

SELECT BATCH_ID, TARGET_TABLE, ROWS_READ, ROWS_LOADED, STATUS
  FROM ETL_AUDIT ORDER BY AUDIT_ID DESC;
```

## 17. Useful Oracle Validation Queries


Check OLTP sales order:

```sql
SELECT *
FROM ard_ops_salesorder
WHERE order_no = '82389099';
```

Check sales fact by order number:

```sql
SELECT *
FROM fact_sales
WHERE sales_order_id IN (
    SELECT order_id
    FROM ard_ops_salesorder
    WHERE order_no = '82389099'
);
```

Check customer in OLTP:

```sql
SELECT *
FROM ard_ops_customer
WHERE customer_nm = 'JERSEY FOODS';
```

Check customer in OLAP:

```sql
SELECT *
FROM dim_customer
WHERE customer_name = 'JERSEY FOODS';
```

Check row counts:

```sql
SELECT 'DIM_CUSTOMER' AS table_name, COUNT(*) AS row_count FROM dim_customer
UNION ALL
SELECT 'DIM_PRODUCT', COUNT(*) FROM dim_product
UNION ALL
SELECT 'FACT_SALES', COUNT(*) FROM fact_sales
UNION ALL
SELECT 'FACT_PACK_PRODUCTION', COUNT(*) FROM fact_pack_production
UNION ALL
SELECT 'FACT_MILL_PRODUCTION', COUNT(*) FROM fact_mill_production;
```

## 18. Presentation Summary


This project converts a raw Excel-based ETL process into a production-style pipeline.

Key improvements:

- Three clear pipelines: OLTP load, OLTP-to-OLAP incremental load, and audit/control.
- Central config file for paths and Oracle settings.
- Single consolidated log file.
- Single consolidated error file.
- Single reconciliation workbook.
- Incremental history workbook that stores only inserted/updated rows.
- Snapshot-based ID preservation to prevent customer/order/product ID shifting.
- OLAP incremental procedure execution.
- Run manifest and run control tracking.
- Cron-based scheduling support.

## 19. Documentation/Presentation Prompt


Use this prompt if you want to generate a polished report or presentation:

```text
Create a professional end-to-end project documentation and presentation for an Ardent Mills ETL pipeline project.

Project details:
- Source data comes from an Excel workbook dropped into the data/ folder, which acts as a work queue.
- The original OLTP ETL package is stored under ardent_mills_etl.
- Production wrappers are stored under production_pipelines.
- There are two production pipelines, driven by one orchestrator:
  1. 01_oltp_load_pipeline.py: takes the workbook from data/, archives it, transforms and validates it, and loads ARD_OPS_* OLTP Oracle tables.
  2. 02_oltp_to_olap_incremental_pipeline.py: runs the OLTP load, then RUN_INCREMENTAL_OLAP_LOAD to load DIM_* and FACT_* tables.
  3. orchestration/run_all.py: runs both stages in order and stops at the first failure.
- A config file named production_pipelines/config/pipeline_config.json stores paths, Oracle details, output locations, and OLAP control settings.
- Logs are appended to production_pipelines/logs/inc_pipeline.log.
- Errors are appended to production_pipelines/errors/inc_pipeline_errors.csv.
- Run history is stored in Oracle: ETL_AUDIT (run summary plus one row per target table), ETL_ERROR (one row per failure), ETL_FILE_REGISTRY (one row per source file, keyed on SHA-256), ETL_LOAD_CONTROL (the incremental watermark).
- Source files are archived to archive/YYYY/MM/DD/ with a timestamp before being parsed; failures go to quarantine/.
- Incremental history is stored in production_pipelines/history/incremental_history.xlsx.
- The latest snapshot baseline is stored in production_pipelines/history/current_snapshot.json.
- Run manifests are stored in production_pipelines/logs/inc_pipeline_manifest.jsonl.
- ID generation has been fixed so generated IDs are preserved from the previous snapshot using business keys instead of row position.
- The project supports scheduling by running orchestration/run_all.py; an empty data/ folder exits 0 so frequent schedules are cheap.

Write the documentation with these sections:
1. Project overview
2. Business problem
3. Architecture
4. Folder structure
5. Config file explanation
6. Pipeline 1 explanation
7. Pipeline 2 explanation
8. Pipeline 3 explanation
9. Logging and error handling
10. Reconciliation
11. Incremental history and snapshot logic
12. ID stability issue and solution
13. Oracle validation queries
14. Testing steps
15. Scheduling/deployment
16. Final conclusion

Make it suitable for presenting to a technical interviewer or project evaluator.
Use clear language, bullet points, and a professional tone.
```
