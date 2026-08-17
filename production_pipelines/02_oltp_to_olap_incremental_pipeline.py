from __future__ import annotations

import argparse
from datetime import datetime

from pipeline_common import (
    CONTROL_PROCESS_NAME,
    DEFAULT_FIRST_LOAD_DATE,
    DEFAULT_ORACLE_CONFIG,
    OLAP_LOAD_ORDER,
    OLAP_TABLES,
    OLTP_TABLES,
    add_common_args,
    configure_logging,
    finish_source_intake,
    intake_source_workbook,
    load_oltp_modules,
    new_batch_id,
    parse_load_date,
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


PIPELINE_NAME = "02_oltp_to_olap_incremental"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OLTP load from the original package, then incremental OLAP procedures."
    )
    add_common_args(parser)
    parser.add_argument("--skip-oltp", action="store_true")
    parser.add_argument("--skip-olap", action="store_true")
    parser.add_argument("--load-date", help="Override previous successful OLAP load date.")
    return parser.parse_args()


def ensure_load_control_row(cursor) -> None:
    cursor.execute(
        """
        MERGE INTO ETL_LOAD_CONTROL tgt
        USING (
            SELECT :process_name AS process_name,
                   :first_load_date AS first_load_date
            FROM dual
        ) src
        ON (tgt.process_name = src.process_name)
        WHEN NOT MATCHED THEN
            INSERT (process_name, last_load_date, last_success_date, status)
            VALUES (src.process_name, src.first_load_date, NULL, 'READY')
        """,
        {
            "process_name": CONTROL_PROCESS_NAME,
            "first_load_date": DEFAULT_FIRST_LOAD_DATE,
        },
    )


def get_control_load_date(conn) -> datetime:
    with conn.cursor() as cursor:
        ensure_load_control_row(cursor)
        cursor.execute(
            """
            SELECT NVL(last_load_date, :first_load_date)
            FROM etl_load_control
            WHERE process_name = :process_name
            """,
            {
                "process_name": CONTROL_PROCESS_NAME,
                "first_load_date": DEFAULT_FIRST_LOAD_DATE,
            },
        )
        row = cursor.fetchone()
    conn.commit()
    return row[0] if row and row[0] else DEFAULT_FIRST_LOAD_DATE


def mark_control_status(conn, status: str, load_start_date: datetime | None = None) -> None:
    with conn.cursor() as cursor:
        ensure_load_control_row(cursor)
        if status == "SUCCESS":
            cursor.execute(
                """
                UPDATE etl_load_control
                   SET last_load_date = :load_start_date,
                       last_success_date = SYSDATE,
                       status = 'SUCCESS'
                 WHERE process_name = :process_name
                """,
                {
                    "process_name": CONTROL_PROCESS_NAME,
                    "load_start_date": load_start_date,
                },
            )
        else:
            cursor.execute(
                """
                UPDATE etl_load_control
                   SET status = :status
                 WHERE process_name = :process_name
                """,
                {"process_name": CONTROL_PROCESS_NAME, "status": status},
            )
    conn.commit()


def oracle_procedure_exists(cursor, procedure_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM user_objects
        WHERE object_name = UPPER(:procedure_name)
          AND object_type = 'PROCEDURE'
          AND status = 'VALID'
        """,
        {"procedure_name": procedure_name},
    )
    return cursor.fetchone()[0] > 0


def run_olap_procedures(open_oracle_connection, load_date: datetime, logger) -> datetime:
    load_start_date = datetime.now()
    with open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
        try:
            with conn.cursor() as cursor:
                if oracle_procedure_exists(cursor, "RUN_INCREMENTAL_OLAP_LOAD"):
                    logger.info(
                        "Running RUN_INCREMENTAL_OLAP_LOAD with LOAD_DATE=%s", load_date
                    )
                    # The wrapper owns the control row: it stamps the watermark from
                    # the database clock and sets SUCCESS/FAILED itself, so the row
                    # stays correct even when the procedure is run outside this
                    # pipeline. Do not overwrite it from the client clock here.
                    cursor.callproc("RUN_INCREMENTAL_OLAP_LOAD", [load_date])
                else:
                    logger.info(
                        "RUN_INCREMENTAL_OLAP_LOAD not found; running individual OLAP procedures"
                    )
                    for procedure_name in OLAP_LOAD_ORDER:
                        logger.info("Running %s with LOAD_DATE=%s", procedure_name, load_date)
                        cursor.callproc(procedure_name, [load_date])
                    mark_control_status(conn, "SUCCESS", load_start_date)
        except Exception:
            conn.rollback()
            try:
                mark_control_status(conn, "FAILED")
            except Exception:
                pass
            raise
    return load_start_date


def main() -> None:
    args = parse_args()
    run_id = timestamp()
    logger = configure_logging(PIPELINE_NAME, run_id)
    modules = load_oltp_modules()
    batch_id = new_batch_id()
    started_at = datetime.now()
    logger.info("Batch id: %s", batch_id)

    intake = None
    excel_path = None
    if not args.skip_oltp:
        intake = intake_source_workbook(modules, args, batch_id, logger)
        if intake.skip_reason:
            logger.info("Nothing to process: %s", intake.skip_reason)
            logger.info("Incremental pipeline finished with no work to do")
            return
        excel_path = intake.path

    raw = None
    tables = None
    summary_df = None
    oltp_counts = None
    olap_counts = None

    try:
        if not args.skip_connection_test:
            ok, message = modules.test_oracle_connection(DEFAULT_ORACLE_CONFIG)
            logger.info("Oracle connection status: %s - %s", ok, message)
            if not ok:
                raise RuntimeError(message)

        if args.load_date:
            load_date = parse_load_date(args.load_date)
        else:
            with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
                load_date = get_control_load_date(conn)
        logger.info("Previous successful OLAP load date: %s", load_date)

        if args.skip_oltp:
            logger.info("Skipping OLTP load")
        else:
            logger.info("Running original packaged OLTP pipeline first")
            raw = modules.load_source_excel(excel_path)
            tables, issues, details = modules.build_all_tables(raw)
            fk_issues = modules.find_foreign_key_issues(tables)
            for issue in fk_issues:
                issues.setdefault(issue["target_table"], []).append(issue)
            summary_df = modules.summary_dataframe(raw, tables, issues)
            if fk_issues:
                raise RuntimeError(f"Foreign-key validation failed with {len(fk_issues)} issue(s).")

            if args.validate_only:
                logger.info("validate-only requested; skipping OLTP and OLAP database writes")
            else:
                modules.run_all_tables(tables, DEFAULT_ORACLE_CONFIG)
                oltp_counts = verify_oracle_row_counts(
                    modules.open_oracle_connection,
                    OLTP_TABLES,
                    DEFAULT_ORACLE_CONFIG,
                )
                history_path, history_rows = update_incremental_history(
                    modules, run_id, PIPELINE_NAME, tables
                )
                logger.info(
                    "Incremental history workbook: %s (%d rows)",
                    history_path,
                    history_rows,
                )

        if args.skip_olap or args.validate_only:
            logger.info("Skipping OLAP step")
        else:
            run_olap_procedures(modules.open_oracle_connection, load_date, logger)
            olap_counts = verify_oracle_row_counts(
                modules.open_oracle_connection,
                OLAP_TABLES,
                DEFAULT_ORACLE_CONFIG,
            )

        recon_path = write_reconciliation_workbook(
            run_id=run_id,
            pipeline_name=PIPELINE_NAME,
            raw=raw,
            tables=tables,
            validation_summary=summary_df,
            oltp_db_counts=oltp_counts,
            olap_db_counts=olap_counts,
        )
        manifest_path = write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {
                "status": "SUCCESS",
                "excel": str(excel_path),
                "load_date": load_date,
                "skip_oltp": args.skip_oltp,
                "skip_olap": args.skip_olap,
                "validate_only": args.validate_only,
                "reconciliation_output": str(recon_path),
            },
        )
        logger.info("Reconciliation workbook: %s", recon_path)
        logger.info("Run manifest: %s", manifest_path)
        if not args.validate_only:
            with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as audit_conn:
                record_audit(
                    audit_conn, batch_id, PIPELINE_NAME, "SUCCESS", started_at, logger,
                    source_object=str(excel_path),
                    target_table="DIM_* / FACT_*",
                    rows_loaded=(
                        int(olap_counts["database_rows"].sum())
                        if olap_counts is not None and not olap_counts.empty
                        else None
                    ),
                )
        if intake is not None:
            finish_source_intake(modules, intake, "SUCCESS", logger)
        logger.info("OLTP-to-OLAP incremental pipeline finished successfully")
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "SUCCESS",
            f"OLTP-to-OLAP incremental pipeline finished successfully. Reconciliation workbook: {recon_path}",
            logger,
        )

    except Exception as exc:
        error_path = write_error_record(PIPELINE_NAME, run_id, "OLTP_TO_OLAP", exc)
        write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {"status": "FAILED", "excel": str(excel_path), "error_file": str(error_path)},
        )
        if not args.validate_only:
            try:
                with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as audit_conn:
                    record_error(
                        audit_conn, batch_id, PIPELINE_NAME, "OLTP_TO_OLAP", exc, logger,
                        target_table="DIM_* / FACT_*",
                    )
                    record_audit(
                        audit_conn, batch_id, PIPELINE_NAME, "FAILED", started_at, logger,
                        source_object=str(excel_path), target_table="DIM_* / FACT_*",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
            except Exception as audit_exc:
                logger.warning("Could not record failure in the database: %s", audit_exc)
        if intake is not None:
            finish_source_intake(
                modules, intake, "FAILED", logger, f"{type(exc).__name__}: {exc}"
            )
        logger.exception("OLTP-to-OLAP pipeline failed. Error file: %s", error_path)
        send_pipeline_alert(
            PIPELINE_NAME,
            run_id,
            "FAILED",
            f"OLTP-to-OLAP pipeline failed. Error file: {error_path}",
            logger,
            exc,
        )
        raise


if __name__ == "__main__":
    main()
