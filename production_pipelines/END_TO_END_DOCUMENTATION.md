# Ardent Mills ETL Pipeline - End-to-End Documentation

## 1. Project Overview

This project implements a production-style ETL pipeline for the Ardent Mills data warehouse.

The source data comes from an Excel workbook. The pipeline transforms that source data into operational OLTP tables named `ARD_OPS_*`, then incrementally loads OLAP dimension and fact tables such as `DIM_CUSTOMER`, `DIM_PRODUCT`, `FACT_SALES`, and other reporting tables.

The project is designed to support:

- Initial and incremental OLTP loading
- Incremental OLTP-to-OLAP loading
- Logging
- Error tracking
- Reconciliation
- Incremental history capture
- Run control/audit tracking
- Scheduling and deployment through cron jobs

## 2. High-Level Architecture

The pipeline follows this flow:

```text
Excel Source File
        |
        v
Original OLTP ETL Package
        |
        v
ARD_OPS_* OLTP Tables
        |
        v
Incremental OLAP Stored Procedures
        |
        v
DIM_* and FACT_* OLAP Tables
        |
        v
Logs, Errors, Reconciliation, History, Audit Control
```

The original OLTP package is kept as the source of truth:

```text
ardent_mills_etl
```

The production wrapper scripts are kept here:

```text
production_pipelines
```

## 3. Main Folder Structure

```text
Ardent_mills/
|
|-- data/
|   |-- Ardent_Mills_Data.xlsx
|
|-- sql/
|   |-- 01_tables.sql
|   |-- 02_procedures.sql
|
|-- ardent_mills_etl/
|   |-- transformers/
|   |-- loaders/
|   |-- utils/
|   |-- config/
|   |-- tests/
|
|-- production_pipelines/
|   |-- 01_oltp_load_pipeline.py
|   |-- 02_oltp_to_olap_incremental_pipeline.py
|   |-- 03_audit_control_pipeline.py
|   |-- pipeline_common.py
|   |-- config/
|   |   |-- pipeline_config.json
|   |-- logs/
|   |-- errors/
|   |-- reconciliation/
|   |-- history/
|   |-- deploy/
|   |-- sql/
|   |-- README.md
|   |-- END_TO_END_DOCUMENTATION.md
```

## 4. Configuration File

The main config file is:

```text
production_pipelines/config/pipeline_config.json
```

This file stores project settings such as:

- Source Excel path
- OLTP package path
- Log file path
- Error file path
- Reconciliation file path
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

1. Reads `Ardent_Mills_Data.xlsx`.
2. Calls the original packaged transformer functions.
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
6. Writes reconciliation output.
7. Updates incremental history after successful database load.

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
4. Runs OLAP incremental procedures.
5. Updates `ETL_LOAD_CONTROL` only after successful completion.
6. Writes logs, manifest, reconciliation, and history.

OLAP procedure order:

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

## 7. Pipeline 3: Audit and Control Pipeline

File:

```text
production_pipelines/03_audit_control_pipeline.py
```

Purpose:

This pipeline creates audit/control outputs and reconciliation checks after pipeline execution.

Main activities:

1. Captures OLTP table row counts.
2. Captures OLAP table row counts.
3. Writes reconciliation results.
4. Appends run status to the control CSV file.
5. Writes success/failure information to the manifest.

Command:

```powershell
py .\production_pipelines\03_audit_control_pipeline.py
```

Command without database counts:

```powershell
py .\production_pipelines\03_audit_control_pipeline.py --skip-db-counts
```

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
- Reconciliation output path
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

## 10. Reconciliation

The reconciliation workbook is:

```text
production_pipelines/reconciliation/inc_pipeline_reconciliation.xlsx
```

It stores reconciliation information in sheets such as:

- `Run_Info`
- `Source_Counts`
- `Transformed_Counts`
- `Validation`
- `OLTP_DB_Counts`
- `OLAP_DB_Counts`

Reconciliation is important because it confirms whether:

- Source rows were read correctly
- Transformation counts match the expected grain
- OLTP tables received data
- OLAP tables received data
- Validation checks passed

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

## 14. Run Control CSV

The control file is:

```text
production_pipelines/logs/etl_run_control.csv
```

It stores audit/control status rows for pipeline runs.

It helps answer:

- Which run completed?
- Which run failed?
- Which reconciliation output belongs to that run?
- Which error file belongs to a failed run?

## 15. Deployment and Cron Scheduling

For production scheduling, this project can be executed using cron jobs on a Linux server or any environment that supports cron.

Recommended daily cron flow:

```text
1. Run the OLTP-to-OLAP incremental pipeline.
2. Run the audit/control pipeline after the incremental pipeline succeeds.
```

Example shell script:

```bash
#!/bin/bash
set -e

cd "/path/to/Ardent Mills project"

python production_pipelines/02_oltp_to_olap_incremental_pipeline.py
python production_pipelines/03_audit_control_pipeline.py
```

Save this as:

```text
production_pipelines/deploy/run_all_production_pipelines.sh
```

Make it executable:

```bash
chmod +x production_pipelines/deploy/run_all_production_pipelines.sh
```

Open cron:

```bash
crontab -e
```

Example: run every day at 2:00 AM:

```cron
0 2 * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

Example: run every 6 hours:

```cron
0 */6 * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

Example: run every weekday at 1:30 AM:

```cron
30 1 * * 1-5 "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

Example: run every minute for testing:

```cron
* * * * * "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/run_all_production_pipelines.sh" >> "/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/logs/cron.log" 2>&1
```

In a real production environment, the cron frequency can be daily, hourly, or based on source file arrival requirements.

## 16. How to Test the Pipeline

### Step 1: Validate transformations only

```powershell
py .\production_pipelines\01_oltp_load_pipeline.py --validate-only
```

Expected result:

- No Oracle load
- Validation summary generated
- Reconciliation workbook updated
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

### Step 4: Test audit/control

```powershell
py .\production_pipelines\03_audit_control_pipeline.py
```

Expected result:

- OLTP and OLAP counts captured
- Reconciliation workbook updated
- Control CSV updated

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
- Source data comes from an Excel workbook named Ardent_Mills_Data.xlsx.
- The original OLTP ETL package is stored under ardent_mills_etl.
- Production wrappers are stored under production_pipelines.
- There are three production pipelines:
  1. 01_oltp_load_pipeline.py: reads Excel, transforms data, validates it, and loads ARD_OPS_* OLTP Oracle tables.
  2. 02_oltp_to_olap_incremental_pipeline.py: runs OLTP load first, then runs incremental OLAP stored procedures to load DIM_* and FACT_* tables.
  3. 03_audit_control_pipeline.py: captures row counts, reconciliation, control status, and audit outputs.
- A config file named production_pipelines/config/pipeline_config.json stores paths, Oracle details, output locations, and OLAP control settings.
- Logs are appended to production_pipelines/logs/inc_pipeline.log.
- Errors are appended to production_pipelines/errors/inc_pipeline_errors.csv.
- Reconciliation is stored in production_pipelines/reconciliation/inc_pipeline_reconciliation.xlsx.
- Incremental history is stored in production_pipelines/history/incremental_history.xlsx.
- The latest snapshot baseline is stored in production_pipelines/history/current_snapshot.json.
- Run manifests are stored in production_pipelines/logs/inc_pipeline_manifest.jsonl.
- Run control status is stored in production_pipelines/logs/etl_run_control.csv.
- ID generation has been fixed so generated IDs are preserved from the previous snapshot using business keys instead of row position.
- The project supports scheduling using cron jobs.

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
