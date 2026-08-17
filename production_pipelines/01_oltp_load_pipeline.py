from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from pipeline_common import (
    DEFAULT_ORACLE_CONFIG,
    DIAGNOSTICS_JSON_FILE,
    OLTP_TABLES,
    VALIDATION_WORKBOOK_FILE,
    add_common_args,
    configure_logging,
    finish_source_intake,
    intake_source_workbook,
    load_oltp_modules,
    new_batch_id,
    record_audit,
    record_error,
    send_pipeline_alert,
    timestamp,
    update_incremental_history,
    verify_oracle_row_counts,
    write_error_record,
    write_reconciliation_workbook,
    write_run_manifest,
)


PIPELINE_NAME = "01_oltp_load"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Excel source data into ARD_OPS OLTP tables.")
    add_common_args(parser)
    parser.add_argument("--validation-output", type=Path, default=None)
    parser.add_argument("--diagnostics-output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id = timestamp()
    logger = configure_logging(PIPELINE_NAME, run_id)
    modules = load_oltp_modules()

    batch_id = new_batch_id()
    started_at = datetime.now()
    logger.info("Batch id: %s", batch_id)

    validation_output = args.validation_output or VALIDATION_WORKBOOK_FILE
    diagnostics_output = args.diagnostics_output or DIAGNOSTICS_JSON_FILE

    intake = intake_source_workbook(modules, args, batch_id, logger)
    if intake.skip_reason:
        logger.info("Nothing to process: %s", intake.skip_reason)
        logger.info("OLTP pipeline finished with no work to do")
        return
    excel_path = intake.path

    try:
        if not args.validate_only and not args.skip_connection_test:
            ok, message = modules.test_oracle_connection(DEFAULT_ORACLE_CONFIG)
            logger.info("Oracle connection status: %s - %s", ok, message)
            if not ok:
                raise RuntimeError(message)

        logger.info("Reading source Excel: %s", excel_path)
        raw = modules.load_source_excel(excel_path)
        logger.info("Source sheet shapes: %s", {k: v.shape for k, v in raw.items()})

        logger.info("Transforming source sheets into ARD_OPS tables")
        tables, issues, details = modules.build_all_tables(raw)
        fk_issues = modules.find_foreign_key_issues(tables)
        for issue in fk_issues:
            issues.setdefault(issue["target_table"], []).append(issue)

        summary_df = modules.summary_dataframe(raw, tables, issues)
        logger.info("Validation summary:\n%s", summary_df.to_string(index=False))

        modules.write_validation_workbook(validation_output, raw, tables, issues, details)
        modules.export_diagnostics_json(diagnostics_output, raw, tables, issues)
        logger.info("Validation workbook: %s", validation_output)
        logger.info("Diagnostics JSON: %s", diagnostics_output)

        db_counts = None
        if args.validate_only:
            logger.info("validate-only requested; skipping Oracle load")
        else:
            if fk_issues:
                raise RuntimeError(f"Foreign-key validation failed with {len(fk_issues)} issue(s).")
            logger.info("Loading ARD_OPS tables with original OLTP pipeline MERGE loader")
            modules.run_all_tables(tables, DEFAULT_ORACLE_CONFIG)
            db_counts = verify_oracle_row_counts(
                modules.open_oracle_connection,
                OLTP_TABLES,
                DEFAULT_ORACLE_CONFIG,
            )
            history_path, history_rows = update_incremental_history(
                modules, run_id, PIPELINE_NAME, tables
            )
            logger.info("Incremental history workbook: %s (%d rows)", history_path, history_rows)

        recon_path = write_reconciliation_workbook(
            run_id=run_id,
            pipeline_name=PIPELINE_NAME,
            raw=raw,
            tables=tables,
            validation_summary=summary_df,
            oltp_db_counts=db_counts,
        )
        manifest_path = write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {
                "status": "SUCCESS",
                "excel": str(excel_path),
                "validation_output": str(validation_output),
                "diagnostics_output": str(diagnostics_output),
                "reconciliation_output": str(recon_path),
                "validate_only": args.validate_only,
            },
        )
        logger.info("Reconciliation workbook: %s", recon_path)
        logger.info("Run manifest: %s", manifest_path)
        if not args.validate_only:
            with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as audit_conn:
                record_audit(
                    audit_conn, batch_id, PIPELINE_NAME, "SUCCESS", started_at, logger,
                    source_object=str(excel_path),
                    target_table="ARD_OPS_*",
                    rows_read=int(sum(len(df) for df in raw.values())),
                    rows_loaded=int(sum(len(df) for df in tables.values())),
                )
        finish_source_intake(modules, intake, "SUCCESS", logger)
        logger.info("OLTP pipeline finished successfully")
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "SUCCESS",
            f"OLTP pipeline finished successfully. Reconciliation workbook: {recon_path}",
            logger,
        )

    except Exception as exc:
        error_path = write_error_record(PIPELINE_NAME, run_id, "OLTP_LOAD", exc)
        write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {"status": "FAILED", "excel": str(excel_path), "error_file": str(error_path)},
        )
        if not args.validate_only:
            try:
                with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as audit_conn:
                    record_error(
                        audit_conn, batch_id, PIPELINE_NAME, "OLTP_LOAD", exc, logger,
                        target_table="ARD_OPS_*",
                    )
                    record_audit(
                        audit_conn, batch_id, PIPELINE_NAME, "FAILED", started_at, logger,
                        source_object=str(excel_path), target_table="ARD_OPS_*",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
            except Exception as audit_exc:
                logger.warning("Could not record failure in the database: %s", audit_exc)
        finish_source_intake(
            modules, intake, "FAILED", logger, f"{type(exc).__name__}: {exc}"
        )
        logger.exception("OLTP pipeline failed. Error file: %s", error_path)
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "FAILED",
            f"OLTP pipeline failed. Error file: {error_path}",
            logger,
            exc,
        )
        raise


if __name__ == "__main__":
    main()
