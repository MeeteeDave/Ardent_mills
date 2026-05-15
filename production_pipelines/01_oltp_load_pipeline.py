from __future__ import annotations

import argparse
from pathlib import Path

from pipeline_common import (
    DEFAULT_ORACLE_CONFIG,
    DIAGNOSTICS_JSON_FILE,
    OLTP_TABLES,
    VALIDATION_WORKBOOK_FILE,
    add_common_args,
    configure_logging,
    load_oltp_modules,
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

    validation_output = args.validation_output or VALIDATION_WORKBOOK_FILE
    diagnostics_output = args.diagnostics_output or DIAGNOSTICS_JSON_FILE

    try:
        if not args.validate_only and not args.skip_connection_test:
            ok, message = modules.test_oracle_connection(DEFAULT_ORACLE_CONFIG)
            logger.info("Oracle connection status: %s - %s", ok, message)
            if not ok:
                raise RuntimeError(message)

        logger.info("Reading source Excel: %s", args.excel)
        raw = modules.load_source_excel(args.excel)
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
                "excel": str(args.excel),
                "validation_output": str(validation_output),
                "diagnostics_output": str(diagnostics_output),
                "reconciliation_output": str(recon_path),
                "validate_only": args.validate_only,
            },
        )
        logger.info("Reconciliation workbook: %s", recon_path)
        logger.info("Run manifest: %s", manifest_path)
        logger.info("OLTP pipeline finished successfully")

    except Exception as exc:
        error_path = write_error_record(PIPELINE_NAME, run_id, "OLTP_LOAD", exc)
        write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {"status": "FAILED", "excel": str(args.excel), "error_file": str(error_path)},
        )
        logger.exception("OLTP pipeline failed. Error file: %s", error_path)
        raise


if __name__ == "__main__":
    main()
