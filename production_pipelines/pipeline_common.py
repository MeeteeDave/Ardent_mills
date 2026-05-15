from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = PROJECT_DIR.parent
CONFIG_FILE = PROJECT_DIR / "production_pipelines" / "config" / "pipeline_config.json"


def load_pipeline_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def configured_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else PROJECT_DIR / path


PIPELINE_CONFIG = load_pipeline_config()
PATH_CONFIG = PIPELINE_CONFIG.get("paths", {})
ORACLE_CONFIG = PIPELINE_CONFIG.get("oracle", {})
OLAP_CONFIG = PIPELINE_CONFIG.get("olap", {})

PIPELINE_DIR = PROJECT_DIR / "production_pipelines"
LOG_DIR = configured_path(PATH_CONFIG.get("log_dir"), PIPELINE_DIR / "logs")
ERROR_DIR = configured_path(PATH_CONFIG.get("error_dir"), PIPELINE_DIR / "errors")
RECON_DIR = configured_path(PATH_CONFIG.get("reconciliation_dir"), PIPELINE_DIR / "reconciliation")
HISTORY_DIR = configured_path(PATH_CONFIG.get("history_dir"), PIPELINE_DIR / "history")
LOG_FILE = configured_path(PATH_CONFIG.get("log_file"), LOG_DIR / "inc_pipeline.log")
ERROR_FILE = configured_path(PATH_CONFIG.get("error_file"), ERROR_DIR / "inc_pipeline_errors.csv")
RECON_FILE = configured_path(
    PATH_CONFIG.get("reconciliation_file"),
    RECON_DIR / "inc_pipeline_reconciliation.xlsx",
)
HISTORY_FILE = configured_path(PATH_CONFIG.get("history_file"), HISTORY_DIR / "incremental_history.xlsx")
SNAPSHOT_FILE = configured_path(PATH_CONFIG.get("snapshot_file"), HISTORY_DIR / "current_snapshot.json")
MANIFEST_FILE = configured_path(
    PATH_CONFIG.get("manifest_file"),
    LOG_DIR / "inc_pipeline_manifest.jsonl",
)
CONTROL_FILE = configured_path(PATH_CONFIG.get("control_file"), LOG_DIR / "etl_run_control.csv")
VALIDATION_WORKBOOK_FILE = configured_path(
    PATH_CONFIG.get("validation_workbook"),
    RECON_DIR / "inc_validation_workbook.xlsx",
)
DIAGNOSTICS_JSON_FILE = configured_path(
    PATH_CONFIG.get("diagnostics_json"),
    RECON_DIR / "inc_diagnostics.json",
)

OLTP_PROJECT_ROOT = configured_path(
    PATH_CONFIG.get("oltp_project_root"),
    PROJECT_DIR / "Ardent mill etl pipline" / "Ardent mill etl pipline",
)
OLTP_PACKAGE_DIR = OLTP_PROJECT_ROOT / "ardent_mills_etl"
DEFAULT_EXCEL_PATH = configured_path(
    PATH_CONFIG.get("source_excel"),
    OLTP_PROJECT_ROOT / "Ardent_Mills_Data.xlsx",
)

DEFAULT_ORACLE_CONFIG = {
    "host": os.getenv("ARDENT_ORACLE_HOST", ORACLE_CONFIG.get("host", "")),
    "port": int(os.getenv("ARDENT_ORACLE_PORT", str(ORACLE_CONFIG.get("port", "1521")))),
    "service_name": os.getenv("ARDENT_ORACLE_SERVICE", ORACLE_CONFIG.get("service_name", "orcl")),
    "username": os.getenv("ARDENT_ORACLE_USER", ORACLE_CONFIG.get("username", "")),
    "password": os.getenv("ARDENT_ORACLE_PASSWORD", ORACLE_CONFIG.get("password", "")),
}

OLTP_TABLES = [
    "ARD_OPS_SITE",
    "ARD_OPS_ITEMCLASS",
    "ARD_OPS_PRODUCT",
    "ARD_OPS_CUSTOMER",
    "ARD_OPS_SHIPTOACCOUNT",
    "ARD_OPS_CARRIER",
    "ARD_OPS_PRODUCTIONMIX",
    "ARD_OPS_MAINTENANCETYPE",
    "ARD_OPS_CLEANINGTYPE",
    "ARD_OPS_PACKLINE",
    "ARD_OPS_BIN",
    "ARD_OPS_PACKRUN",
    "ARD_OPS_MILLRUN",
    "ARD_OPS_SALESORDER",
    "ARD_OPS_SALESORDERLINE",
    "ARD_OPS_WORKORDER",
    "ARD_OPS_BINCLEANINGLOG",
    "ARD_OPS_FILLORDER",
]

OLAP_TABLES = [
    "DIM_DATE",
    "DIM_SITE",
    "DIM_PRODUCT",
    "DIM_CUSTOMER",
    "DIM_SHIPTO",
    "DIM_CARRIER",
    "DIM_PACKLINE",
    "DIM_MAINTENANCE_TYPE",
    "DIM_BIN",
    "DIM_CLEANING_TYPE",
    "DIM_PRODUCTION_MIX",
    "FACT_SALES",
    "FACT_PACK_PRODUCTION",
    "FACT_MILL_PRODUCTION",
    "FACT_MAINTENANCE",
    "FACT_BIN_CLEANING",
]

OLAP_DIM_PROCEDURES = [
    "INC_LOAD_DIM_DATE",
    "INC_LOAD_DIM_SITE",
    "INC_LOAD_DIM_PRODUCT",
    "INC_LOAD_DIM_CUSTOMER",
    "INC_LOAD_DIM_SHIPTO",
    "INC_LOAD_DIM_CARRIER",
    "INC_LOAD_DIM_PACKLINE",
    "INC_LOAD_DIM_MAINTENANCE_TYPE",
    "INC_LOAD_DIM_BIN",
    "INC_LOAD_DIM_CLEANING_TYPE",
    "INC_LOAD_DIM_PRODUCTION_MIX",
]

OLAP_FACT_PROCEDURES = [
    "INC_LOAD_FACT_SALES",
    "INC_LOAD_FACT_PACK_PRODUCTION",
    "INC_LOAD_FACT_MILL_PRODUCTION",
    "INC_LOAD_FACT_MAINTENANCE",
    "INC_LOAD_FACT_BIN_CLEANING",
]

OLAP_LOAD_ORDER = OLAP_DIM_PROCEDURES + OLAP_FACT_PROCEDURES
CONTROL_PROCESS_NAME = OLAP_CONFIG.get("control_process_name", "OLAP_INCREMENTAL_LOAD")
DEFAULT_FIRST_LOAD_DATE = datetime.strptime(
    OLAP_CONFIG.get("default_first_load_date", "1900-01-01"),
    "%Y-%m-%d",
)


@dataclass
class OltpModules:
    load_source_excel: Any
    build_all_tables: Any
    summary_dataframe: Any
    write_validation_workbook: Any
    export_diagnostics_json: Any
    find_foreign_key_issues: Any
    run_all_tables: Any
    test_oracle_connection: Any
    open_oracle_connection: Any
    build_change_report: Any
    load_snapshot: Any
    save_snapshot: Any


def ensure_directories() -> None:
    for path in [LOG_DIR, ERROR_DIR, RECON_DIR, HISTORY_DIR, CONFIG_FILE.parent]:
        path.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def configure_logging(pipeline_name: str, run_id: str) -> logging.Logger:
    ensure_directories()
    logger = logging.getLogger(pipeline_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.info("=" * 120)
    logger.info("Pipeline started: %s | run_id=%s", pipeline_name, run_id)
    logger.info("Log file: %s", LOG_FILE)
    return logger


def write_error_record(
    pipeline_name: str,
    run_id: str,
    stage: str,
    exc: BaseException,
) -> Path:
    ensure_directories()
    is_new = not ERROR_FILE.exists()
    with ERROR_FILE.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "pipeline_name",
                "stage",
                "error_type",
                "error_message",
                "traceback",
                "created_at",
            ],
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "run_id": run_id,
                "pipeline_name": pipeline_name,
                "stage": stage,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    return ERROR_FILE


def load_oltp_modules() -> OltpModules:
    if not OLTP_PACKAGE_DIR.exists():
        raise FileNotFoundError(f"Original OLTP package not found: {OLTP_PACKAGE_DIR}")
    package_path = str(OLTP_PACKAGE_DIR)
    if package_path not in sys.path:
        sys.path.insert(0, package_path)

    from loaders.oracle_loader import (  # type: ignore
        open_oracle_connection,
        run_all_tables,
        test_oracle_connection,
    )
    from transformers.pipeline import build_all_tables  # type: ignore
    from utils.excel_reader import load_source_excel  # type: ignore
    from utils.validation import (  # type: ignore
        export_diagnostics_json,
        find_foreign_key_issues,
        summary_dataframe,
        write_validation_workbook,
    )
    from utils.change_tracker import (  # type: ignore
        build_change_report,
        load_snapshot,
        save_snapshot,
    )

    return OltpModules(
        load_source_excel=load_source_excel,
        build_all_tables=build_all_tables,
        summary_dataframe=summary_dataframe,
        write_validation_workbook=write_validation_workbook,
        export_diagnostics_json=export_diagnostics_json,
        find_foreign_key_issues=find_foreign_key_issues,
        run_all_tables=run_all_tables,
        test_oracle_connection=test_oracle_connection,
        open_oracle_connection=open_oracle_connection,
        build_change_report=build_change_report,
        load_snapshot=load_snapshot,
        save_snapshot=save_snapshot,
    )


def parse_load_date(value: str) -> datetime:
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Use load date format YYYY-MM-DD HH:MM:SS.")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--skip-connection-test", action="store_true")


def table_counts_from_dataframes(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"table_name": name, "transformed_rows": len(df)} for name, df in tables.items()]
    )


def source_counts(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"source_sheet": name, "source_rows": len(df)} for name, df in raw.items()]
    )


def verify_oracle_row_counts(
    open_oracle_connection: Any,
    table_names: list[str],
    oracle_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    oracle_config = oracle_config or DEFAULT_ORACLE_CONFIG
    rows: list[dict[str, Any]] = []
    with open_oracle_connection(oracle_config) as conn:
        with conn.cursor() as cursor:
            for table_name in table_names:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    rows.append(
                        {
                            "table_name": table_name,
                            "database_rows": cursor.fetchone()[0],
                            "status": "OK",
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "table_name": table_name,
                            "database_rows": None,
                            "status": f"ERROR: {exc}",
                        }
                    )
    return pd.DataFrame(rows)


def write_reconciliation_workbook(
    run_id: str,
    pipeline_name: str,
    raw: dict[str, pd.DataFrame] | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    validation_summary: pd.DataFrame | None = None,
    oltp_db_counts: pd.DataFrame | None = None,
    olap_db_counts: pd.DataFrame | None = None,
) -> Path:
    ensure_directories()
    sheets: dict[str, pd.DataFrame] = {
        "Run_Info": pd.DataFrame(
            [{
                "run_id": run_id,
                "pipeline_name": pipeline_name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }]
        )
    }
    if raw is not None:
        sheets["Source_Counts"] = source_counts(raw).assign(
            run_id=run_id, pipeline_name=pipeline_name
        )
    if tables is not None:
        sheets["Transformed_Counts"] = table_counts_from_dataframes(tables).assign(
            run_id=run_id, pipeline_name=pipeline_name
        )
    if validation_summary is not None:
        sheets["Validation"] = validation_summary.assign(
            run_id=run_id, pipeline_name=pipeline_name
        )
    if oltp_db_counts is not None:
        sheets["OLTP_DB_Counts"] = oltp_db_counts.assign(
            run_id=run_id, pipeline_name=pipeline_name
        )
    if olap_db_counts is not None:
        sheets["OLAP_DB_Counts"] = olap_db_counts.assign(
            run_id=run_id, pipeline_name=pipeline_name
        )

    existing: dict[str, pd.DataFrame] = {}
    if RECON_FILE.exists():
        existing = pd.read_excel(RECON_FILE, sheet_name=None)

    with pd.ExcelWriter(RECON_FILE, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            old = existing.get(sheet_name)
            combined = pd.concat([old, df], ignore_index=True) if old is not None else df
            combined.to_excel(writer, sheet_name=sheet_name, index=False)
        for sheet_name, df in existing.items():
            if sheet_name not in sheets:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return RECON_FILE


def update_incremental_history(
    modules: OltpModules,
    run_id: str,
    pipeline_name: str,
    tables: dict[str, pd.DataFrame],
) -> tuple[Path, int]:
    ensure_directories()
    previous_snapshot = modules.load_snapshot(SNAPSHOT_FILE)
    if not previous_snapshot:
        previous_snapshot = modules.load_snapshot(
            OLTP_PACKAGE_DIR / "Ardent_Mills_ETL_Snapshot.json"
        )
    if not previous_snapshot:
        modules.save_snapshot(SNAPSHOT_FILE, tables)
        return HISTORY_FILE, 0

    _, changes_df = modules.build_change_report(previous_snapshot, tables)

    if changes_df.empty:
        modules.save_snapshot(SNAPSHOT_FILE, tables)
        return HISTORY_FILE, 0

    history_df = changes_df[changes_df["change_type"].isin(["INSERT", "UPDATE"])].copy()
    if history_df.empty:
        modules.save_snapshot(SNAPSHOT_FILE, tables)
        return HISTORY_FILE, 0

    history_df.insert(0, "run_id", run_id)
    history_df.insert(1, "pipeline_name", pipeline_name)
    history_df.insert(2, "captured_at", datetime.now().isoformat(timespec="seconds"))

    try:
        existing = pd.DataFrame()
        if HISTORY_FILE.exists():
            existing_sheets = pd.read_excel(HISTORY_FILE, sheet_name=None)
            existing = existing_sheets.get("Incremental_History", pd.DataFrame())

        combined = pd.concat([existing, history_df], ignore_index=True)
        with pd.ExcelWriter(HISTORY_FILE, engine="openpyxl") as writer:
            combined.to_excel(writer, sheet_name="Incremental_History", index=False)
    except PermissionError:
        logging.getLogger(pipeline_name).warning(
            "Incremental history workbook is locked: %s. "
            "Close the file and rerun; snapshot was not advanced, so these changes will be captured next run.",
            HISTORY_FILE,
        )
        return HISTORY_FILE, 0

    modules.save_snapshot(SNAPSHOT_FILE, tables)

    return HISTORY_FILE, len(history_df)


def write_run_manifest(pipeline_name: str, run_id: str, values: dict[str, Any]) -> Path:
    ensure_directories()
    payload = {
        "pipeline_name": pipeline_name,
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **values,
    }
    with MANIFEST_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")
    return MANIFEST_FILE
