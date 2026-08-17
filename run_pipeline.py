"""
===============================================================================
 Script Name   : run_pipeline.py
 Project       : Ardent Mills ETL
 Description   : The whole pipeline, in one place. Run this file and nothing
                 else.

                 Two stages, and the order is not cosmetic:

                   STAGING    Excel workbook -> ARD_OPS_* tables
                              Read, transform, validate, then MERGE. MERGE and
                              not INSERT, so re-running the same file is safe.

                   WAREHOUSE  ARD_OPS_* -> DIM_* and FACT_*
                              One call to RUN_INCREMENTAL_OLAP_LOAD, which
                              loads all 11 dimensions before all 5 facts. A
                              fact resolves its foreign keys by looking the
                              business key up in the dimension, so a fact built
                              on a stale dimension drops or misassigns rows.

                 Incremental loading is driven by dates, not by file names:
                 the loader stamps CREATED_DATE/UPDATED_DATE on rows it writes,
                 and the OLAP procedures pick up only rows newer than the
                 watermark held in ETL_LOAD_CONTROL.

                 Run history goes to the database, never to a local file:
                 ETL_AUDIT (one summary row per run plus one row per table),
                 ETL_ERROR (one row per failure), ETL_FILE_REGISTRY (one row
                 per source file).

 Usage         : py run_pipeline.py
                 py run_pipeline.py --validate-only     # no database writes
                 py run_pipeline.py --only staging
                 py run_pipeline.py --force             # reload the same file
                 py run_pipeline.py --excel other.xlsx
===============================================================================
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent / "pipelines"))

from pipeline_common import (  # noqa: E402
    CONTROL_PROCESS_NAME,
    DEFAULT_FIRST_LOAD_DATE,
    DEFAULT_ORACLE_CONFIG,
    OLAP_TABLES,
    OLTP_TABLES,
    add_common_args,
    configure_logging,
    load_oltp_modules,
    new_batch_id,
    parse_load_date,
    record_audit,
    record_error,
    record_table_audit,
    release_file,
    send_pipeline_alert,
    take_next_file,
    timestamp,
    update_load_history,
    verify_oracle_row_counts,
    write_error_record,
    write_run_manifest,
)

PIPELINE_NAME = "ardent_mills_etl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Ardent Mills ETL: Excel -> ARD_OPS_* -> DIM_*/FACT_*."
    )
    add_common_args(parser)
    parser.add_argument(
        "--only",
        choices=["staging", "warehouse"],
        help="Run a single stage instead of both.",
    )
    parser.add_argument(
        "--load-date",
        help='Override the watermark, e.g. "1900-01-01 00:00:00" to reload everything.',
    )
    return parser.parse_args()


def read_watermark(conn, logger) -> datetime:
    """The date the OLAP procedures load from: rows newer than this are picked up.

    The row is created on first use so a brand new database still works.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            MERGE INTO ETL_LOAD_CONTROL tgt
            USING (SELECT :process_name AS process_name FROM dual) src
               ON (tgt.process_name = src.process_name)
            WHEN NOT MATCHED THEN
                INSERT (process_name, last_load_date, last_success_date, status)
                VALUES (:process_name, :first_load_date, NULL, 'READY')
            """,
            {"process_name": CONTROL_PROCESS_NAME, "first_load_date": DEFAULT_FIRST_LOAD_DATE},
        )
        cursor.execute(
            "SELECT NVL(last_load_date, :first_load_date) FROM etl_load_control "
            "WHERE process_name = :process_name",
            {"process_name": CONTROL_PROCESS_NAME, "first_load_date": DEFAULT_FIRST_LOAD_DATE},
        )
        row = cursor.fetchone()
    conn.commit()
    return row[0] if row and row[0] else DEFAULT_FIRST_LOAD_DATE


def load_staging(modules, args, excel_path, run_id, logger):
    """Excel -> ARD_OPS_*. Returns (raw sheets, built tables, validation summary)."""
    logger.info("STAGING: reading %s", excel_path)
    raw = modules.load_source_excel(excel_path)
    logger.info("Source sheet shapes: %s", {k: v.shape for k, v in raw.items()})

    logger.info("STAGING: transforming source sheets into ARD_OPS tables")
    tables, issues, details = modules.build_all_tables(raw)

    fk_issues = modules.find_foreign_key_issues(tables)
    for issue in fk_issues:
        issues.setdefault(issue["target_table"], []).append(issue)
    summary_df = modules.summary_dataframe(raw, tables, issues)
    logger.info("Validation summary:\n%s", summary_df.to_string(index=False))

    if args.validate_only:
        logger.info("validate-only requested; skipping the Oracle load")
        return raw, tables, summary_df

    # A broken foreign key means a fact would later fail its dimension lookup,
    # so stop here rather than loading data the warehouse cannot join.
    if fk_issues:
        raise RuntimeError(f"Foreign-key validation failed with {len(fk_issues)} issue(s).")

    logger.info("STAGING: loading ARD_OPS tables with the MERGE loader")
    modules.run_all_tables(tables, DEFAULT_ORACLE_CONFIG)
    verify_oracle_row_counts(modules.open_oracle_connection, OLTP_TABLES, DEFAULT_ORACLE_CONFIG)

    history_path, history_rows = update_load_history(modules, run_id, PIPELINE_NAME, tables)
    logger.info("Load history workbook: %s (%d rows)", history_path, history_rows)
    return raw, tables, summary_df


def load_warehouse(modules, load_date, logger):
    """ARD_OPS_* -> DIM_*/FACT_*, by calling the one Oracle procedure."""
    with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
        with conn.cursor() as cursor:
            logger.info("WAREHOUSE: RUN_INCREMENTAL_OLAP_LOAD with LOAD_DATE=%s", load_date)
            # The procedure owns ETL_LOAD_CONTROL: it stamps the watermark from
            # the database clock and sets SUCCESS/FAILED itself, so the row stays
            # correct even when the procedure is run by hand outside this script.
            cursor.callproc("RUN_INCREMENTAL_OLAP_LOAD", [load_date])
    return verify_oracle_row_counts(
        modules.open_oracle_connection, OLAP_TABLES, DEFAULT_ORACLE_CONFIG
    )


def main() -> None:
    args = parse_args()
    run_id = timestamp()
    logger = configure_logging(PIPELINE_NAME, run_id)
    modules = load_oltp_modules()

    batch_id = new_batch_id()
    started_at = datetime.now()
    logger.info("Batch id: %s", batch_id)

    run_staging = args.only in (None, "staging")
    run_warehouse = args.only in (None, "warehouse") and not args.validate_only

    intake = None
    excel_path = None
    if run_staging:
        intake = take_next_file(modules, args, batch_id, logger)
        if intake.skip_reason:
            # An empty queue is success, not failure: normal for a scheduled run.
            logger.info("Nothing to process: %s", intake.skip_reason)
            return
        excel_path = intake.path

    raw = tables = summary_df = olap_counts = None

    try:
        if not args.validate_only and not args.skip_connection_test:
            ok, message = modules.test_oracle_connection(DEFAULT_ORACLE_CONFIG)
            logger.info("Oracle connection status: %s - %s", ok, message)
            if not ok:
                raise RuntimeError(message)

        if run_staging:
            raw, tables, summary_df = load_staging(modules, args, excel_path, run_id, logger)

        if run_warehouse:
            if args.load_date:
                load_date = parse_load_date(args.load_date)
            else:
                with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
                    load_date = read_watermark(conn, logger)
            logger.info("Loading warehouse rows changed since %s", load_date)
            olap_counts = load_warehouse(modules, load_date, logger)

        write_run_manifest(
            PIPELINE_NAME,
            run_id,
            {
                "status": "SUCCESS",
                "excel": str(excel_path),
                "only": args.only,
                "validate_only": args.validate_only,
            },
        )

        if not args.validate_only:
            with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
                record_audit(
                    conn, batch_id, PIPELINE_NAME, "SUCCESS", started_at, logger,
                    source_object=str(excel_path),
                    target_table="ARD_OPS_* -> DIM_*/FACT_*",
                    rows_read=int(sum(len(df) for df in raw.values())) if raw else None,
                    rows_loaded=(
                        int(olap_counts["database_rows"].sum())
                        if olap_counts is not None and not olap_counts.empty
                        else None
                    ),
                )
                logger.info("Run audit row written (batch %s)", batch_id)
                # one row per table: the grain check for this run
                record_table_audit(conn, batch_id, PIPELINE_NAME, summary_df, started_at, logger)

        if intake is not None:
            release_file(modules, intake, "SUCCESS", logger)
        logger.info("Pipeline finished successfully")
        send_pipeline_alert(PIPELINE_NAME, run_id, "SUCCESS", "Pipeline finished successfully.", logger)

    except Exception as exc:
        error_path = write_error_record(PIPELINE_NAME, run_id, "ETL", exc)
        write_run_manifest(
            PIPELINE_NAME, run_id,
            {"status": "FAILED", "excel": str(excel_path), "error_file": str(error_path)},
        )
        if not args.validate_only:
            try:
                with modules.open_oracle_connection(DEFAULT_ORACLE_CONFIG) as conn:
                    record_error(conn, batch_id, PIPELINE_NAME, "ETL", exc, logger)
                    record_audit(
                        conn, batch_id, PIPELINE_NAME, "FAILED", started_at, logger,
                        source_object=str(excel_path),
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
            except Exception as audit_exc:
                logger.warning("Could not record the failure in the database: %s", audit_exc)

        if intake is not None:
            release_file(modules, intake, "FAILED", logger, f"{type(exc).__name__}: {exc}")
        logger.exception("Pipeline failed. Error file: %s", error_path)
        send_pipeline_alert(
            PIPELINE_NAME, run_id, "FAILED", f"Pipeline failed. Error file: {error_path}",
            logger, exc,
        )
        raise


if __name__ == "__main__":
    main()
