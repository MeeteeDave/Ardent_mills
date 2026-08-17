from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import smtplib
import sys
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = PROJECT_DIR.parent
CONFIG_FILE = PROJECT_DIR / "production_pipelines" / "config" / "pipeline_config.json"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(PROJECT_DIR / ".env")


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
HISTORY_DIR = configured_path(PATH_CONFIG.get("history_dir"), PIPELINE_DIR / "history")
LOG_FILE = configured_path(PATH_CONFIG.get("log_file"), LOG_DIR / "inc_pipeline.log")
ERROR_FILE = configured_path(PATH_CONFIG.get("error_file"), ERROR_DIR / "inc_pipeline_errors.csv")
HISTORY_FILE = configured_path(PATH_CONFIG.get("history_file"), HISTORY_DIR / "incremental_history.xlsx")
SNAPSHOT_FILE = configured_path(PATH_CONFIG.get("snapshot_file"), HISTORY_DIR / "current_snapshot.json")
MANIFEST_FILE = configured_path(
    PATH_CONFIG.get("manifest_file"),
    LOG_DIR / "inc_pipeline_manifest.jsonl",
)

OLTP_PROJECT_ROOT = configured_path(
    PATH_CONFIG.get("oltp_project_root"),
    PROJECT_DIR,
)
OLTP_PACKAGE_DIR = OLTP_PROJECT_ROOT / "ardent_mills_etl"
DEFAULT_EXCEL_PATH = configured_path(
    PATH_CONFIG.get("source_excel"),
    PROJECT_DIR / "data" / "Ardent_Mills_Data.xlsx",
)

DEFAULT_ORACLE_CONFIG = {
    "host": os.getenv("ARDENT_ORACLE_HOST", ORACLE_CONFIG.get("host", "")),
    "port": int(os.getenv("ARDENT_ORACLE_PORT", str(ORACLE_CONFIG.get("port", "1521")))),
    "service_name": os.getenv("ARDENT_ORACLE_SERVICE", ORACLE_CONFIG.get("service_name", "orcl")),
    "username": os.getenv("ARDENT_ORACLE_USER", ORACLE_CONFIG.get("username", "")),
    "password": os.getenv("ARDENT_ORACLE_PASSWORD", ORACLE_CONFIG.get("password", "")),
}


def getenv_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def getenv_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


ALERT_CONFIG = {
    "enable_email": getenv_bool("ARDENT_ALERT_ENABLE_EMAIL", False),
    "smtp_server": os.getenv("ARDENT_ALERT_SMTP_SERVER", ""),
    "smtp_port": getenv_int("ARDENT_ALERT_SMTP_PORT", 587),
    "sender_email": os.getenv("ARDENT_ALERT_SENDER_EMAIL", ""),
    "sender_password": os.getenv("ARDENT_ALERT_SENDER_PASSWORD", ""),
    "recipient_emails": getenv_list("ARDENT_ALERT_RECIPIENT_EMAILS"),
}


def send_pipeline_alert(
    pipeline_name: str,
    run_id: str,
    status: str,
    message: str,
    logger: logging.Logger,
    exc: BaseException | None = None,
) -> None:
    if not ALERT_CONFIG["enable_email"]:
        logger.info("Email alert skipped because ARDENT_ALERT_ENABLE_EMAIL is disabled")
        return

    missing = [
        key
        for key in ["smtp_server", "sender_email", "sender_password", "recipient_emails"]
        if not ALERT_CONFIG[key]
    ]
    if missing:
        logger.warning("Email alert skipped because SMTP config is missing: %s", ", ".join(missing))
        return

    body = [
        f"Pipeline: {pipeline_name}",
        f"Run ID: {run_id}",
        f"Status: {status}",
        "",
        message,
    ]
    if exc is not None:
        body.extend(["", f"Exception: {type(exc).__name__}: {exc}", "", traceback.format_exc()])

    msg = MIMEText("\n".join(body))
    msg["Subject"] = f"ETL {status}: {pipeline_name}"
    msg["From"] = ALERT_CONFIG["sender_email"]
    msg["To"] = ", ".join(ALERT_CONFIG["recipient_emails"])

    try:
        with smtplib.SMTP(ALERT_CONFIG["smtp_server"], ALERT_CONFIG["smtp_port"], timeout=30) as server:
            server.starttls()
            server.login(ALERT_CONFIG["sender_email"], ALERT_CONFIG["sender_password"])
            server.sendmail(
                ALERT_CONFIG["sender_email"],
                ALERT_CONFIG["recipient_emails"],
                msg.as_string(),
            )
        logger.info("Email alert sent: %s", msg["Subject"])
    except Exception as alert_exc:
        logger.exception("Failed to send email alert: %s", alert_exc)


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
    for path in [LOG_DIR, ERROR_DIR, HISTORY_DIR, CONFIG_FILE.parent]:
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
    parser.add_argument("--excel", type=Path, default=None,
                        help="Process this workbook instead of the one in data/.")
    parser.add_argument("--force", action="store_true",
                        help="Reload even if these exact bytes already loaded.")
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


# ---------------------------------------------------------------- ETL audit
# Run history lives in the database, not in local CSV/Excel files: a file on one
# machine is invisible to everyone else and was lost with the rest of the
# working copy. ETL_AUDIT holds one row per pipeline run, ETL_ERROR one row per
# failure, and ETL_LOAD_CONTROL is the watermark the OLAP procedures read.
#
# Auditing must never break a load. Every write here is wrapped: a failure to
# record history is logged and swallowed, so the pipeline result stands on its
# own.

def new_batch_id() -> str:
    """One id per pipeline run, stamped on its audit and error rows."""
    return uuid.uuid4().hex


def record_audit(
    conn,
    batch_id: str,
    pipeline_name: str,
    status: str,
    started_at: datetime,
    logger: logging.Logger,
    *,
    source_object: str | None = None,
    target_table: str | None = None,
    rows_read: int | None = None,
    rows_loaded: int | None = None,
    rows_inserted: int | None = None,
    rows_updated: int | None = None,
    rows_unchanged: int | None = None,
    rows_rejected: int | None = None,
    error_message: str | None = None,
) -> None:
    finished_at = datetime.now()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ETL_AUDIT (
                    BATCH_ID, PIPELINE_NAME, SOURCE_OBJECT, TARGET_TABLE,
                    ROWS_READ, ROWS_LOADED, ROWS_INSERTED, ROWS_UPDATED,
                    ROWS_UNCHANGED, ROWS_REJECTED, STATUS, ERROR_MESSAGE,
                    STARTED_AT, FINISHED_AT, DURATION_SECONDS
                ) VALUES (
                    :batch_id, :pipeline_name, :source_object, :target_table,
                    :rows_read, :rows_loaded, :rows_inserted, :rows_updated,
                    :rows_unchanged, :rows_rejected, :status, :error_message,
                    :started_at, :finished_at, :duration
                )
                """,
                {
                    "batch_id": batch_id,
                    "pipeline_name": pipeline_name,
                    "source_object": source_object,
                    "target_table": target_table,
                    "rows_read": rows_read,
                    "rows_loaded": rows_loaded,
                    "rows_inserted": rows_inserted,
                    "rows_updated": rows_updated,
                    "rows_unchanged": rows_unchanged,
                    "rows_rejected": rows_rejected,
                    "status": status,
                    "error_message": (error_message or "")[:4000] or None,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration": round((finished_at - started_at).total_seconds(), 2),
                },
            )
        conn.commit()
        logger.info("Audit row written: %s %s (batch %s)", pipeline_name, status, batch_id)
    except Exception as exc:
        logger.warning("Could not write ETL_AUDIT row: %s", exc)


def record_error(
    conn,
    batch_id: str,
    pipeline_name: str,
    stage: str,
    exc: BaseException,
    logger: logging.Logger,
    *,
    target_table: str | None = None,
    record_key: str | None = None,
) -> None:
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ETL_ERROR (
                    BATCH_ID, PIPELINE_NAME, STAGE, TARGET_TABLE,
                    RECORD_KEY, ERROR_TYPE, ERROR_MESSAGE, ERROR_DETAIL
                ) VALUES (
                    :batch_id, :pipeline_name, :stage, :target_table,
                    :record_key, :error_type, :error_message, :error_detail
                )
                """,
                {
                    "batch_id": batch_id,
                    "pipeline_name": pipeline_name,
                    "stage": stage,
                    "target_table": target_table,
                    "record_key": record_key,
                    "error_type": type(exc).__name__[:200],
                    "error_message": str(exc)[:4000],
                    "error_detail": traceback.format_exc(),
                },
            )
        conn.commit()
        logger.info("Error row written to ETL_ERROR (batch %s)", batch_id)
    except Exception as write_exc:
        logger.warning("Could not write ETL_ERROR row: %s", write_exc)


def get_watermark(conn, process_name: str) -> datetime | None:
    """Read the incremental watermark from ETL_LOAD_CONTROL."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT LAST_LOAD_DATE FROM ETL_LOAD_CONTROL WHERE PROCESS_NAME = :p",
            {"p": process_name},
        )
        row = cursor.fetchone()
    return row[0] if row else None


# ------------------------------------------------- source file intake/archive
# data/ is a work queue: it holds only files still waiting to be processed.
#
# take_next_file() does the whole intake in one readable pass:
#   find the file -> hash it -> skip if already loaded -> archive the raw bytes
#   -> record it in ETL_FILE_REGISTRY -> hand back the archived copy to read.
#
# The raw bytes are archived BEFORE anything parses them, because the archive is
# the replay source: if the transformer crashes, what landed must still exist.
#
# release_file() closes the queue entry when the run ends.

ARCHIVE_DIR = configured_path(PATH_CONFIG.get("archive_dir"), PROJECT_DIR / "archive")
QUARANTINE_DIR = configured_path(PATH_CONFIG.get("quarantine_dir"), PROJECT_DIR / "quarantine")
DATA_DIR = configured_path(PATH_CONFIG.get("data_dir"), PROJECT_DIR / "data")

# Failures that mean "try again later" rather than "this file is bad". Only a
# bad file leaves the queue: quarantining after a network blip would empty
# data/, and every later run would report "nothing to process" while looking
# perfectly healthy.
RETRYABLE_ERRORS = (
    "DPY-6005", "DPY-4011", "DPY-3010",      # driver: connect / lost / timeout
    "ORA-12154", "ORA-12170", "ORA-12541",   # TNS: resolve / timeout / listener
    "ORA-12514", "ORA-01033", "ORA-03113",   # service / starting up / channel
    "ORA-03114", "ORA-28000", "TNS:",
    "OperationalError", "cannot connect", "connection refused", "timed out",
)


@dataclass
class SourceIntake:
    """What a run is processing, and what to clean up when it finishes."""
    path: Path | None = None           # the archived copy, which the run reads
    original: Path | None = None       # the file in data/, cleared on success
    file_id: int | None = None         # its ETL_FILE_REGISTRY row
    skip_reason: str | None = None     # set when there is nothing to do


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def take_next_file(modules, args, batch_id: str, logger: logging.Logger) -> SourceIntake:
    """Take the workbook waiting in data/, archive it, and register it."""
    # --excel is an explicit override: the caller owns that file, so it is
    # neither archived nor cleared.
    if getattr(args, "excel", None):
        logger.info("Using explicit --excel override: %s", args.excel)
        return SourceIntake(path=Path(args.excel))

    waiting = sorted(
        p for p in DATA_DIR.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$")
    )
    if not waiting:
        # An empty queue is success, not failure - normal for a scheduled run.
        return SourceIntake(skip_reason=f"no .xlsx waiting in {DATA_DIR}")
    if len(waiting) > 1:
        names = ", ".join(p.name for p in waiting)
        raise RuntimeError(
            f"{len(waiting)} workbooks in {DATA_DIR} ({names}). "
            "Leave exactly one, or pass --excel to choose explicitly."
        )

    original = waiting[0]
    file_hash = file_sha256(original)
    logger.info("Source file: %s (sha256 %s...)", original.name, file_hash[:12])

    # validate-only must not touch the database or the queue
    if getattr(args, "validate_only", False):
        logger.info("validate-only: reading in place, not archiving")
        return SourceIntake(path=original)

    with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn, conn.cursor() as cur:
        # Loading identical bytes again is safe for the data - every load is a
        # MERGE - but it stamps UPDATED_DATE on every row it touches, and that
        # column is what the INC_LOAD_* procedures filter on. A repeat load
        # would push the whole dataset through the OLAP layer for nothing.
        cur.execute(
            """SELECT ARCHIVE_PATH, TO_CHAR(PROCESSED_AT, 'YYYY-MM-DD HH24:MI:SS')
                 FROM ETL_FILE_REGISTRY
                WHERE FILE_HASH = :h AND STATUS = 'SUCCESS'
                ORDER BY FILE_ID DESC FETCH FIRST 1 ROWS ONLY""",
            {"h": file_hash},
        )
        already = cur.fetchone()
        if already and not getattr(args, "force", False):
            return SourceIntake(
                original=original,
                skip_reason=f"identical file already loaded at {already[1]} "
                            f"(archived: {already[0]}). Use --force to reload.",
            )
        if already:
            logger.warning("--force: reloading a file already loaded at %s", already[1])

        # archive the raw bytes, date-partitioned and timestamped
        stamp = datetime.now()
        target_dir = ARCHIVE_DIR / f"{stamp:%Y}" / f"{stamp:%m}" / f"{stamp:%d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        archived = target_dir / f"{original.stem}_{stamp:%Y-%m-%d_%H-%M-%S}{original.suffix}"
        shutil.copy2(original, archived)
        if archived.stat().st_size != original.stat().st_size:
            raise RuntimeError(f"Archive copy size mismatch: {archived}")
        logger.info("Archived source file: %s", archived)

        # SIZE is an Oracle reserved word, so bind names are prefixed
        new_file_id = cur.var(int)
        cur.execute(
            """INSERT INTO ETL_FILE_REGISTRY
                   (FILE_NAME, FILE_HASH, FILE_SIZE, ARCHIVE_PATH, STATUS, BATCH_ID)
               VALUES (:file_name, :file_hash, :file_size, :archive_path,
                       'IN_PROGRESS', :batch_id)
               RETURNING FILE_ID INTO :new_file_id""",
            {
                "file_name": original.name,
                "file_hash": file_hash,
                "file_size": original.stat().st_size,
                "archive_path": str(archived),
                "batch_id": batch_id,
                "new_file_id": new_file_id,
            },
        )
        conn.commit()
        file_id = int(new_file_id.getvalue()[0])

    # the run reads the archived copy: it is immutable for the rest of the run
    return SourceIntake(path=archived, original=original, file_id=file_id)


def release_file(
    modules,
    intake: SourceIntake,
    status: str,
    logger: logging.Logger,
    error_message: str | None = None,
) -> None:
    """Close the queue entry: clear data/ on success, quarantine a bad file."""
    if intake.file_id is None and intake.original is None:
        return

    if intake.file_id is not None:
        try:
            with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE ETL_FILE_REGISTRY
                          SET STATUS = :status,
                              PROCESSED_AT = SYSTIMESTAMP,
                              ERROR_MESSAGE = :error_message
                        WHERE FILE_ID = :file_id""",
                    {
                        "status": status,
                        "error_message": (error_message or "")[:4000] or None,
                        "file_id": intake.file_id,
                    },
                )
                conn.commit()
            logger.info("File registry updated: FILE_ID=%s %s", intake.file_id, status)
        except Exception as exc:
            logger.warning("Could not update the file registry: %s", exc)

    if intake.original is None or not intake.original.exists():
        return

    if status == "SUCCESS":
        intake.original.unlink()
        logger.info("Removed %s from the data folder (archived copy retained)",
                    intake.original.name)
        return

    message = (error_message or "").lower()
    if any(marker.lower() in message for marker in RETRYABLE_ERRORS):
        logger.warning(
            "Leaving %s in the data folder to retry: the failure looks like an "
            "infrastructure problem, not a bad file (%s)",
            intake.original.name, (error_message or "")[:120],
        )
        return

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    target = QUARANTINE_DIR / (
        f"{intake.original.stem}_{datetime.now():%Y-%m-%d_%H-%M-%S}{intake.original.suffix}"
    )
    shutil.move(str(intake.original), str(target))
    logger.warning("Moved failed file to quarantine: %s", target)


def record_table_audit(
    conn,
    batch_id: str,
    pipeline_name: str,
    summary_df: "pd.DataFrame",
    started_at: datetime,
    logger: logging.Logger,
) -> int:
    """Write one ETL_AUDIT row per target table from the validation summary.

    This is what replaced the reconciliation workbook: the same per-table grain
    checks, in the database where every run can be compared, instead of an Excel
    file that only existed on the machine that produced it.
    """
    if summary_df is None or summary_df.empty:
        return 0

    written = 0
    for _, row in summary_df.iterrows():
        passed = str(row.get("status", "")).upper() == "PASS"
        record_audit(
            conn,
            batch_id,
            pipeline_name,
            "SUCCESS" if passed else "FAILED",
            started_at,
            logger,
            source_object=str(row.get("source_sheet") or ""),
            target_table=str(row.get("target_table") or ""),
            rows_read=_safe_int(row.get("source_rows")),
            rows_loaded=_safe_int(row.get("actual_target_rows")),
            error_message=None if passed else str(row.get("top_reason") or "")[:4000],
        )
        written += 1
    logger.info("Wrote %d per-table audit rows", written)
    return written


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
