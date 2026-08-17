"""
utils/change_tracker.py
Track run-to-run transformed-table changes and export an audit workbook.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config.table_specs import LOAD_ORDER, TABLE_SPECS
from utils.helpers import utc_now_naive

AUDIT_COLUMNS = {"created_date", "created_by", "updated_date", "updated_by"}
LOGGER = logging.getLogger("ardent_etl.change_tracker")
CHANGE_TRACKING_KEYS: dict[str, list[str]] = {
    "ARD_OPS_Site": ["site_id"],
    "ARD_OPS_ItemClass": ["item_class_desc"],
    "ARD_OPS_Product": ["product_id"],
    "ARD_OPS_Customer": ["customer_nm"],
    "ARD_OPS_ShipToAccount": ["ship_to_id"],
    "ARD_OPS_Carrier": ["carrier_code"],
    "ARD_OPS_ProductionMix": ["production_mix_code"],
    "ARD_OPS_MaintenanceType": ["maintenance_type"],
    "ARD_OPS_CleaningType": ["cleaning_type_id"],
    "ARD_OPS_PackLine": ["site_id", "line_name"],
    "ARD_OPS_Bin": ["bin_id"],
    "ARD_OPS_PackRun": ["pack_run_id"],
    "ARD_OPS_MillRun": ["mill_run_id"],
    "ARD_OPS_SalesOrder": ["order_no"],
    "ARD_OPS_SalesOrderLine": ["order_line_id"],
    "ARD_OPS_WorkOrder": ["wo_no"],
    "ARD_OPS_BinCleaningLog": ["cleaning_log_id"],
    "ARD_OPS_FillOrder": ["fill_order_id"],
}
IDENTITY_MATCH_KEYS: dict[str, list[str]] = {
    "ARD_OPS_Site": ["site_id"],
    "ARD_OPS_ItemClass": ["item_class_id"],
    "ARD_OPS_Product": ["product_pk"],
    "ARD_OPS_Customer": ["customer_id"],
    "ARD_OPS_ShipToAccount": ["ship_to_id"],
    "ARD_OPS_Carrier": ["carrier_id"],
    "ARD_OPS_ProductionMix": ["production_mix_id"],
    "ARD_OPS_MaintenanceType": ["maintenance_type_id"],
    "ARD_OPS_CleaningType": ["cleaning_type_pk"],
    "ARD_OPS_PackLine": ["line_id"],
    "ARD_OPS_Bin": ["bin_pk"],
    "ARD_OPS_PackRun": ["pack_run_id"],
    "ARD_OPS_MillRun": ["mill_run_id"],
    "ARD_OPS_SalesOrder": ["order_id"],
    "ARD_OPS_SalesOrderLine": ["order_line_id"],
    "ARD_OPS_WorkOrder": ["workorder_pk"],
    "ARD_OPS_BinCleaningLog": ["cleaning_log_id"],
    "ARD_OPS_FillOrder": ["fill_order_id"],
}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return value


def _display_value(value: Any) -> str:
    normalized = _normalize_value(value)
    return "" if normalized is None else str(normalized)


def _key_string(key_cols: list[str], row: dict[str, Any]) -> str:
    return " | ".join(f"{col}={_display_value(row.get(col))}" for col in key_cols)


def _change_key_columns(table_name: str) -> list[str]:
    return CHANGE_TRACKING_KEYS.get(table_name, TABLE_SPECS[table_name].business_key)


def _identity_key_columns(table_name: str) -> list[str]:
    return IDENTITY_MATCH_KEYS.get(table_name, [])


def _record_key_tuple(key_cols: list[str], record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(col) for col in key_cols)


def _build_record_map(records: list[dict[str, Any]], key_cols: list[str]) -> dict[tuple[Any, ...], dict[str, Any]]:
    record_map: dict[tuple[Any, ...], dict[str, Any]] = {}
    if not key_cols:
        return record_map
    for record in records:
        key = _record_key_tuple(key_cols, record)
        if any(value is None for value in key):
            continue
        record_map[key] = record
    return record_map


def _snapshot_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if col not in AUDIT_COLUMNS]


def _table_snapshot(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = _snapshot_columns(df)
    records = []
    for row in df[cols].to_dict(orient="records"):
        records.append({col: _normalize_value(value) for col, value in row.items()})
    return records


def load_snapshot(snapshot_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    path = Path(snapshot_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(snapshot_path: str | Path, tables: dict[str, pd.DataFrame]) -> Path:
    path = Path(snapshot_path)
    payload = {
        table_name: _table_snapshot(tables[table_name])
        for table_name in LOAD_ORDER
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def build_change_report(
    previous_snapshot: dict[str, list[dict[str, Any]]],
    current_tables: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    change_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for table_name in LOAD_ORDER:
        key_cols = _change_key_columns(table_name)
        identity_cols = _identity_key_columns(table_name)
        current_records = _table_snapshot(current_tables[table_name])
        previous_records = previous_snapshot.get(table_name, [])
        current_identity_map = _build_record_map(current_records, identity_cols)
        previous_identity_map = _build_record_map(previous_records, identity_cols)
        matched_current_identity_keys: set[tuple[Any, ...]] = set()
        matched_previous_identity_keys: set[tuple[Any, ...]] = set()

        inserted = updated = deleted = 0
        if identity_cols:
            shared_identity_keys = sorted(
                set(current_identity_map) & set(previous_identity_map),
                key=lambda item: tuple("" if v is None else str(v) for v in item),
            )
            for identity_key in shared_identity_keys:
                current_record = current_identity_map[identity_key]
                previous_record = previous_identity_map[identity_key]
                matched_current_identity_keys.add(identity_key)
                matched_previous_identity_keys.add(identity_key)
                record_key = _key_string(key_cols, current_record)

                compare_cols = sorted(set(previous_record) | set(current_record))
                row_changed = False
                for col in compare_cols:
                    old_value = previous_record.get(col)
                    new_value = current_record.get(col)
                    if old_value != new_value:
                        row_changed = True
                        change_rows.append(
                            {
                                "table_name": table_name,
                                "record_key": record_key,
                                "change_type": "UPDATE",
                                "column_name": col,
                                "old_value": _display_value(old_value),
                                "new_value": _display_value(new_value),
                            }
                        )
                if row_changed:
                    updated += 1

        unmatched_current_records = [
            record
            for record in current_records
            if _record_key_tuple(identity_cols, record) not in matched_current_identity_keys
        ] if identity_cols else list(current_records)
        unmatched_previous_records = [
            record
            for record in previous_records
            if _record_key_tuple(identity_cols, record) not in matched_previous_identity_keys
        ] if identity_cols else list(previous_records)

        current_map = _build_record_map(unmatched_current_records, key_cols)
        previous_map = _build_record_map(unmatched_previous_records, key_cols)

        for key in sorted(set(current_map) | set(previous_map), key=lambda item: tuple("" if v is None else str(v) for v in item)):
            current_record = current_map.get(key)
            previous_record = previous_map.get(key)
            record_key = _key_string(key_cols, current_record or previous_record or {})

            if previous_record is None and current_record is not None:
                inserted += 1
                change_rows.append(
                    {
                        "table_name": table_name,
                        "record_key": record_key,
                        "change_type": "INSERT",
                        "column_name": "(new record)",
                        "old_value": "",
                        "new_value": json.dumps(current_record, default=str),
                    }
                )
                continue

            if current_record is None and previous_record is not None:
                deleted += 1
                change_rows.append(
                    {
                        "table_name": table_name,
                        "record_key": record_key,
                        "change_type": "DELETE",
                        "column_name": "(deleted record)",
                        "old_value": json.dumps(previous_record, default=str),
                        "new_value": "",
                    }
                )
                continue

            compare_cols = sorted(set(previous_record) | set(current_record))
            row_changed = False
            for col in compare_cols:
                old_value = previous_record.get(col)
                new_value = current_record.get(col)
                if old_value != new_value:
                    row_changed = True
                    change_rows.append(
                        {
                            "table_name": table_name,
                            "record_key": record_key,
                            "change_type": "UPDATE",
                            "column_name": col,
                            "old_value": _display_value(old_value),
                            "new_value": _display_value(new_value),
                        }
                    )
            if row_changed:
                updated += 1

        summary_rows.append(
            {
                "table_name": table_name,
                "inserted_records": inserted,
                "updated_records": updated,
                "deleted_records": deleted,
                "total_changes": inserted + updated + deleted,
            }
        )

    return pd.DataFrame(summary_rows), pd.DataFrame(change_rows)


def write_change_audit_workbook(
    output_path: str | Path,
    summary_df: pd.DataFrame,
    changes_df: pd.DataFrame,
) -> Path:
    requested_path = Path(output_path)
    path = requested_path
    try:
        return _write_change_audit_workbook(path, summary_df, changes_df)
    except PermissionError:
        timestamp = utc_now_naive().strftime("%Y%m%d_%H%M%S")
        fallback_path = requested_path.with_name(f"{requested_path.stem}_{timestamp}{requested_path.suffix}")
        LOGGER.warning(
            "Change audit workbook is locked: %s. Writing to fallback file instead: %s",
            requested_path,
            fallback_path,
        )
        return _write_change_audit_workbook(fallback_path, summary_df, changes_df)


def _write_change_audit_workbook(
    path: Path,
    summary_df: pd.DataFrame,
    changes_df: pd.DataFrame,
) -> Path:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        if changes_df.empty:
            pd.DataFrame(
                [
                    {
                        "table_name": "",
                        "record_key": "",
                        "change_type": "NO_CHANGES",
                        "column_name": "",
                        "old_value": "",
                        "new_value": "",
                    }
                ]
            ).to_excel(writer, sheet_name="Changes", index=False)
        else:
            changes_df.to_excel(writer, sheet_name="Changes", index=False)
    return path
