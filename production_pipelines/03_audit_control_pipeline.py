from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_common import (
    CONTROL_FILE,
    DEFAULT_ORACLE_CONFIG,
    OLAP_TABLES,
    OLTP_TABLES,
    configure_logging,
    load_oltp_modules,
    send_pipeline_alert,
    timestamp,
    verify_oracle_row_counts,
    write_error_record,
    write_reconciliation_workbook,
    write_run_manifest,
)


PIPELINE_NAME = "03_audit_control"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive local ETL history files and produce audit/control row-count outputs."
    )
    parser.add_argument("--skip-db-counts", action="store_true")
    return parser.parse_args()


def append_control_csv(run_id: str, status: str, artifacts: dict[str, str]) -> Path:
    path = CONTROL_FILE
    row = {
        "run_id": run_id,
        "pipeline_name": PIPELINE_NAME,
        "status": status,
        **artifacts,
    }
    df = pd.DataFrame([row])
    if path.exists():
        df.to_csv(path, mode="a", index=False, header=False)
    else:
        df.to_csv(path, index=False)
    return path


def main() -> None:
    args = parse_args()
    run_id = timestamp()
    logger = configure_logging(PIPELINE_NAME, run_id)
    modules = load_oltp_modules()

    try:
        logger.info("Running audit/control reconciliation")

        oltp_counts = None
        olap_counts = None
        if args.skip_db_counts:
            logger.info("Skipping database row counts")
        else:
            oltp_counts = verify_oracle_row_counts(
                modules.open_oracle_connection,
                OLTP_TABLES,
                DEFAULT_ORACLE_CONFIG,
            )
            olap_counts = verify_oracle_row_counts(
                modules.open_oracle_connection,
                OLAP_TABLES,
                DEFAULT_ORACLE_CONFIG,
            )

        recon_path = write_reconciliation_workbook(
            run_id=run_id,
            pipeline_name=PIPELINE_NAME,
            oltp_db_counts=oltp_counts,
            olap_db_counts=olap_counts,
        )
        control_csv = append_control_csv(
            run_id,
            "SUCCESS",
            {"reconciliation_output": str(recon_path)},
        )
        manifest_path = write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {
                "status": "SUCCESS",
                "reconciliation_output": str(recon_path),
                "control_csv": str(control_csv),
            },
        )
        logger.info("Reconciliation workbook: %s", recon_path)
        logger.info("Control CSV: %s", control_csv)
        logger.info("Run manifest: %s", manifest_path)
        logger.info("Audit/control pipeline finished successfully")
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "SUCCESS",
            f"Audit/control pipeline finished successfully. Reconciliation workbook: {recon_path}",
            logger,
        )

    except Exception as exc:
        error_path = write_error_record(PIPELINE_NAME, run_id, "AUDIT_CONTROL", exc)
        control_csv = append_control_csv(run_id, "FAILED", {"error_file": str(error_path)})
        write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {"status": "FAILED", "error_file": str(error_path), "control_csv": str(control_csv)},
        )
        logger.exception("Audit/control pipeline failed. Error file: %s", error_path)
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "FAILED",
            f"Audit/control pipeline failed. Error file: {error_path}",
            logger,
            exc,
        )
        raise


if __name__ == "__main__":
    main()
