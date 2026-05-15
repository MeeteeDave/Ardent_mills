"""
Ardent Mills ETL Pipeline — main entry point.
Incremental / Upsert load via Oracle MERGE.
Duplicates are rejected at every stage before DB write.

Usage:
    python main.py --excel path/to/Ardent_Mills_Data.xlsx
    python main.py --excel path/to/Ardent_Mills_Data.xlsx --table ARD_OPS_Customer
    python main.py --excel path/to/Ardent_Mills_Data.xlsx --validate-only
    python main.py --excel path/to/Ardent_Mills_Data.xlsx --skip-validation-write
"""

import argparse
import logging
import sys
from pathlib import Path
import smtplib
from email.mime.text import MIMEText

from config.settings import ORACLE_CONFIG, EXCEL_FILE_PATH, VALIDATION_WORKBOOK_PATH, DIAGNOSTICS_JSON_PATH, ALERT_CONFIG
from config.settings import CHANGE_AUDIT_WORKBOOK_PATH, CHANGE_SNAPSHOT_PATH
from loaders.oracle_loader import run_all_tables, run_single_table, test_oracle_connection
from transformers.pipeline import build_all_tables
from utils.change_tracker import build_change_report, load_snapshot, save_snapshot, write_change_audit_workbook
from utils.excel_reader import load_source_excel
from utils.validation import (
    write_validation_workbook,
    export_diagnostics_json,
    find_foreign_key_issues,
    summary_dataframe,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
LOGGER = logging.getLogger("ardent_etl.main")


def send_alert(message, error_type="ERROR", exc=None):
    """
    Send an alert message. Logs the alert and sends email if configured.
    """
    alert_msg = f"ALERT [{error_type}]: {message}"
    if exc:
        import traceback
        alert_msg += f"\nException: {str(exc)}\nTraceback:\n{traceback.format_exc()}"
    LOGGER.error(alert_msg)

    # Send email if enabled
    if ALERT_CONFIG.get("enable_email", False):
        try:
            msg = MIMEText(alert_msg)
            msg['Subject'] = f"ETL Alert: {error_type}"
            msg['From'] = ALERT_CONFIG["sender_email"]
            msg['To'] = ", ".join(ALERT_CONFIG["recipient_emails"])

            server = smtplib.SMTP(ALERT_CONFIG["smtp_server"], ALERT_CONFIG["smtp_port"])
            server.starttls()
            server.login(ALERT_CONFIG["sender_email"], ALERT_CONFIG["sender_password"])
            server.sendmail(ALERT_CONFIG["sender_email"], ALERT_CONFIG["recipient_emails"], msg.as_string())
            server.quit()
            LOGGER.info("Alert email sent successfully.")
        except Exception as email_exc:
            LOGGER.error("Failed to send alert email: %s", str(email_exc))


def parse_args():
    parser = argparse.ArgumentParser(description="Ardent Mills ETL Pipeline")
    parser.add_argument("--excel", type=Path, default=EXCEL_FILE_PATH, help="Path to source Excel file")
    parser.add_argument("--table", type=str, default=None, help="Load a single table (e.g. ARD_OPS_Customer)")
    parser.add_argument("--validate-only", action="store_true", help="Transform and validate only; skip Oracle load")
    parser.add_argument("--skip-connection-test", action="store_true", help="Skip Oracle connection test at startup")
    parser.add_argument("--skip-validation-write", action="store_true", help="Skip writing the validation Excel workbook")
    return parser.parse_args()


def main():
    try:
        args = parse_args()

        # ── 1. Oracle connection test ──────────────────────────────────────────────
        if not args.validate_only:
            if not args.skip_connection_test:
                LOGGER.info("Testing Oracle connection …")
                ok, msg = test_oracle_connection(ORACLE_CONFIG)
                if not ok:
                    error_msg = f"Oracle connection FAILED: {msg}"
                    send_alert(error_msg, "CONNECTION_ERROR")
                    sys.exit(1)
                LOGGER.info("Oracle connection OK")

        # ── 2. Extract ─────────────────────────────────────────────────────────────
        try:
            LOGGER.info("Loading Excel: %s", args.excel)
            raw = load_source_excel(args.excel)
            LOGGER.info("Sheets loaded: %s", {k: v.shape for k, v in raw.items()})
        except Exception as e:
            error_msg = f"Failed to extract data from Excel: {str(e)}"
            send_alert(error_msg, "EXTRACTION_ERROR", e)
            raise

        # ── 3. Transform ───────────────────────────────────────────────────────────
        try:
            LOGGER.info("Transforming all tables …")
            tables, issues, details = build_all_tables(raw)

            fk_issues = find_foreign_key_issues(tables)
            for issue in fk_issues:
                issues.setdefault(issue["target_table"], []).append(issue)

            previous_snapshot = load_snapshot(CHANGE_SNAPSHOT_PATH)
            change_summary_df, changes_df = build_change_report(previous_snapshot, tables)
            LOGGER.info("Writing change audit workbook → %s", CHANGE_AUDIT_WORKBOOK_PATH)
            write_change_audit_workbook(CHANGE_AUDIT_WORKBOOK_PATH, change_summary_df, changes_df)
        except Exception as e:
            error_msg = f"Failed to transform data: {str(e)}"
            send_alert(error_msg, "TRANSFORMATION_ERROR", e)
            raise

        # ── 4. Validate ────────────────────────────────────────────────────────────
        try:
            if not args.skip_validation_write:
                LOGGER.info("Writing validation workbook → %s", VALIDATION_WORKBOOK_PATH)
                write_validation_workbook(VALIDATION_WORKBOOK_PATH, raw, tables, issues, details)
            export_diagnostics_json(DIAGNOSTICS_JSON_PATH, raw, tables, issues)

            summary = summary_dataframe(raw, tables, issues)
            LOGGER.info("\n%s", summary[["target_table", "actual_target_rows", "status"]].to_string(index=False))

            if args.validate_only:
                LOGGER.info("--validate-only flag set; skipping Oracle load.")
                save_snapshot(CHANGE_SNAPSHOT_PATH, tables)
                send_alert("OLTP Data validation completed successfully", "SUCCESS")
                return

            if fk_issues:
                error_msg = f"Foreign key integrity validation failed: {len(fk_issues)} issue(s) found."
                send_alert(error_msg, "VALIDATION_ERROR")
                LOGGER.error("Skipping Oracle load due to unresolved FK issues.")
                return
        except Exception as e:
            error_msg = f"Failed during validation: {str(e)}"
            send_alert(error_msg, "VALIDATION_ERROR", e)
            raise

        # ── 5. Load ────────────────────────────────────────────────────────────────
        try:
            if args.table:
                LOGGER.info("Loading single table: %s", args.table)
                run_single_table(tables, args.table, ORACLE_CONFIG)
            else:
                LOGGER.info("Loading all tables incrementally …")
                run_all_tables(tables, ORACLE_CONFIG)

            save_snapshot(CHANGE_SNAPSHOT_PATH, tables)
            LOGGER.info("ETL pipeline complete.")
            send_alert("OLTP Data pipeline completed successfully", "SUCCESS")
        except Exception as e:
            error_msg = f"Failed to load data into Oracle: {str(e)}"
            send_alert(error_msg, "LOAD_ERROR", e)
            raise

    except Exception as e:
        error_msg = f"ETL pipeline failed with unexpected error: {str(e)}"
        send_alert(error_msg, "GENERAL_ERROR", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
