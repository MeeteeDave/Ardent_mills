# Ardent Mills ETL Pipeline

Incremental / upsert ETL from Excel → Oracle using `MERGE`.

## Project Structure

```
ardent_mills_etl/
├── main.py                        # Entry point — run this
├── requirements.txt
├── config/
│   ├── settings.py                # Oracle creds, file paths, constants
│   └── table_specs.py             # All 18 table definitions (keys, grain, load order)
├── transformers/
│   ├── dimensions.py              # 11 dimension table builders
│   ├── facts.py                   # 7 fact/transaction table builders
│   └── pipeline.py                # Orchestrates all builders in FK-safe order
├── loaders/
│   └── oracle_loader.py           # Oracle MERGE upsert, connection helpers
├── utils/
│   ├── helpers.py                 # normalize_text, add_audit, parse_site_short_name, etc.
│   ├── excel_reader.py            # load_source_excel
│   └── validation.py             # Validation workbook + diagnostics JSON
├── sql/
│   └── create_tables.sql          # DDL — run once to create all Oracle tables
└── tests/
    └── test_transformers.py       # Unit tests
```

## Quick Start

```bash
pip install -r requirements.txt

# 1. Edit config/settings.py with your Oracle credentials and Excel path
# 2. Create Oracle tables (run once)
#    sqlplus user/pass@dsn @sql/create_tables.sql

# 3. Run the full pipeline
python main.py --excel path/to/Ardent_Mills_Data.xlsx

# Validate only (no Oracle write)
python main.py --excel path/to/Ardent_Mills_Data.xlsx --validate-only

# Load a single table
python main.py --excel path/to/Ardent_Mills_Data.xlsx --table ARD_OPS_Customer
```

## Incremental Load Logic

Each run uses Oracle `MERGE`:
- **WHEN MATCHED** → UPDATE all non-key columns with fresh values
- **WHEN NOT MATCHED** → INSERT new row

Re-running the pipeline is safe — it never creates duplicates.

## Duplicate Prevention (3 layers)

| Layer | Where | How |
|-------|-------|-----|
| Transformer | `transformers/dimensions.py`, `transformers/facts.py` | `drop_duplicates(subset=[business_key])` before returning |
| Loader | `loaders/oracle_loader.py → run_single_table` | `drop_duplicates(subset=loader_key)` before MERGE |
| Database | Oracle MERGE | `ON` clause guarantees exactly one matched row |

### Customer table fix
The original notebook assigned sequential `customer_id` values **before** deduplicating,
which could produce duplicate IDs if two rows had the same `CUSTOMER_NM`.
The fix (`transformers/dimensions.py → build_customer`) now:
1. Deduplicates on `customer_nm` first
2. Then assigns `customer_id` values — guaranteeing uniqueness on both the natural key and the surrogate key

## Outputs

| File | Description |
|------|-------------|
| `Ardent_Mills_ETL_Test_Cases.xlsx` | Validation workbook (Summary, Test_Cases, Issues, Issue_Details, per-table previews) |
| `Ardent_Mills_ETL_Change_Audit.xlsx` | Run-to-run change audit showing table, record key, change type, changed column, old value, and new value |
| `Ardent_Mills_ETL_Diagnostics.json` | Machine-readable diagnostics |
| `Ardent_Mills_ETL_Snapshot.json` | Baseline snapshot used to detect changes on the next run |
