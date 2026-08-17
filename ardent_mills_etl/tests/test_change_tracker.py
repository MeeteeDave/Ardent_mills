import pandas as pd
import pytest

from utils.change_tracker import build_change_report, write_change_audit_workbook


def test_build_change_report_detects_insert_update_delete():
    previous_snapshot = {
        "ARD_OPS_Site": [{"site_id": 1, "site_name": "Albany"}],
        "ARD_OPS_ItemClass": [],
        "ARD_OPS_Product": [],
        "ARD_OPS_Customer": [{"customer_id": 3000, "customer_nm": "Acme Corp"}],
        "ARD_OPS_ShipToAccount": [],
        "ARD_OPS_Carrier": [],
        "ARD_OPS_ProductionMix": [],
        "ARD_OPS_MaintenanceType": [],
        "ARD_OPS_CleaningType": [],
        "ARD_OPS_PackLine": [],
        "ARD_OPS_Bin": [],
        "ARD_OPS_PackRun": [],
        "ARD_OPS_MillRun": [],
        "ARD_OPS_SalesOrder": [],
        "ARD_OPS_SalesOrderLine": [],
        "ARD_OPS_WorkOrder": [],
        "ARD_OPS_BinCleaningLog": [],
        "ARD_OPS_FillOrder": [{"fill_order_id": 38000, "order_number": 10}],
    }
    current_tables = {
        "ARD_OPS_Site": pd.DataFrame([{"site_id": 1, "site_name": "Ayer"}]),
        "ARD_OPS_ItemClass": pd.DataFrame(columns=["item_class_id", "item_class_desc"]),
        "ARD_OPS_Product": pd.DataFrame(columns=["product_pk", "product_id", "product_desc", "item_class_id"]),
        "ARD_OPS_Customer": pd.DataFrame([{"customer_id": 3001, "customer_nm": "Beta LLC"}]),
        "ARD_OPS_ShipToAccount": pd.DataFrame(columns=["ship_to_id"]),
        "ARD_OPS_Carrier": pd.DataFrame(columns=["carrier_id"]),
        "ARD_OPS_ProductionMix": pd.DataFrame(columns=["production_mix_id"]),
        "ARD_OPS_MaintenanceType": pd.DataFrame(columns=["maintenance_type_id"]),
        "ARD_OPS_CleaningType": pd.DataFrame(columns=["cleaning_type_pk"]),
        "ARD_OPS_PackLine": pd.DataFrame(columns=["line_id"]),
        "ARD_OPS_Bin": pd.DataFrame(columns=["bin_pk"]),
        "ARD_OPS_PackRun": pd.DataFrame(columns=["pack_run_id"]),
        "ARD_OPS_MillRun": pd.DataFrame(columns=["mill_run_id"]),
        "ARD_OPS_SalesOrder": pd.DataFrame(columns=["order_id", "order_no"]),
        "ARD_OPS_SalesOrderLine": pd.DataFrame(columns=["order_line_id", "order_no"]),
        "ARD_OPS_WorkOrder": pd.DataFrame(columns=["workorder_pk", "wo_no"]),
        "ARD_OPS_BinCleaningLog": pd.DataFrame(columns=["cleaning_log_id"]),
        "ARD_OPS_FillOrder": pd.DataFrame(columns=["fill_order_id", "order_number"]),
    }

    summary_df, changes_df = build_change_report(previous_snapshot, current_tables)

    site_summary = summary_df[summary_df["table_name"] == "ARD_OPS_Site"].iloc[0]
    customer_summary = summary_df[summary_df["table_name"] == "ARD_OPS_Customer"].iloc[0]
    fill_summary = summary_df[summary_df["table_name"] == "ARD_OPS_FillOrder"].iloc[0]

    assert site_summary["updated_records"] == 1
    assert customer_summary["inserted_records"] == 1
    assert customer_summary["deleted_records"] == 1
    assert fill_summary["deleted_records"] == 1
    assert ((changes_df["table_name"] == "ARD_OPS_Site") & (changes_df["change_type"] == "UPDATE")).any()
    assert ((changes_df["table_name"] == "ARD_OPS_Customer") & (changes_df["change_type"] == "INSERT")).any()
    assert ((changes_df["table_name"] == "ARD_OPS_Customer") & (changes_df["change_type"] == "DELETE")).any()


def test_build_change_report_uses_customer_name_as_stable_change_key():
    previous_snapshot = {
        "ARD_OPS_Site": [],
        "ARD_OPS_ItemClass": [],
        "ARD_OPS_Product": [],
        "ARD_OPS_Customer": [{"customer_id": 3094, "customer_nm": "ORLANDO FOODS INC"}],
        "ARD_OPS_ShipToAccount": [],
        "ARD_OPS_Carrier": [],
        "ARD_OPS_ProductionMix": [],
        "ARD_OPS_MaintenanceType": [],
        "ARD_OPS_CleaningType": [],
        "ARD_OPS_PackLine": [],
        "ARD_OPS_Bin": [],
        "ARD_OPS_PackRun": [],
        "ARD_OPS_MillRun": [],
        "ARD_OPS_SalesOrder": [],
        "ARD_OPS_SalesOrderLine": [],
        "ARD_OPS_WorkOrder": [],
        "ARD_OPS_BinCleaningLog": [],
        "ARD_OPS_FillOrder": [],
    }
    current_tables = {
        "ARD_OPS_Site": pd.DataFrame(columns=["site_id"]),
        "ARD_OPS_ItemClass": pd.DataFrame(columns=["item_class_id", "item_class_desc"]),
        "ARD_OPS_Product": pd.DataFrame(columns=["product_pk", "product_id", "product_desc", "item_class_id"]),
        "ARD_OPS_Customer": pd.DataFrame([{"customer_id": 3094, "customer_nm": "ORLANDO FOODS INC4199"}]),
        "ARD_OPS_ShipToAccount": pd.DataFrame(columns=["ship_to_id"]),
        "ARD_OPS_Carrier": pd.DataFrame(columns=["carrier_id", "carrier_code"]),
        "ARD_OPS_ProductionMix": pd.DataFrame(columns=["production_mix_id", "production_mix_code"]),
        "ARD_OPS_MaintenanceType": pd.DataFrame(columns=["maintenance_type_id", "maintenance_type"]),
        "ARD_OPS_CleaningType": pd.DataFrame(columns=["cleaning_type_pk", "cleaning_type_id"]),
        "ARD_OPS_PackLine": pd.DataFrame(columns=["line_id", "site_id", "line_name"]),
        "ARD_OPS_Bin": pd.DataFrame(columns=["bin_pk", "bin_id"]),
        "ARD_OPS_PackRun": pd.DataFrame(columns=["pack_run_id"]),
        "ARD_OPS_MillRun": pd.DataFrame(columns=["mill_run_id"]),
        "ARD_OPS_SalesOrder": pd.DataFrame(columns=["order_id", "order_no"]),
        "ARD_OPS_SalesOrderLine": pd.DataFrame(columns=["order_line_id", "order_no"]),
        "ARD_OPS_WorkOrder": pd.DataFrame(columns=["workorder_pk", "wo_no"]),
        "ARD_OPS_BinCleaningLog": pd.DataFrame(columns=["cleaning_log_id"]),
        "ARD_OPS_FillOrder": pd.DataFrame(columns=["fill_order_id"]),
    }

    _, changes_df = build_change_report(previous_snapshot, current_tables)

    customer_changes = changes_df[changes_df["table_name"] == "ARD_OPS_Customer"]
    assert len(customer_changes) == 1
    assert set(customer_changes["change_type"]) == {"UPDATE"}
    assert customer_changes["record_key"].tolist() == ["customer_nm=ORLANDO FOODS INC4199"]
    assert customer_changes["column_name"].tolist() == ["customer_nm"]


def test_build_change_report_treats_same_customer_id_name_change_as_update():
    previous_snapshot = {
        "ARD_OPS_Site": [],
        "ARD_OPS_ItemClass": [],
        "ARD_OPS_Product": [],
        "ARD_OPS_Customer": [{"customer_id": 3094, "customer_nm": "ORLANDO FOODS INC4199"}],
        "ARD_OPS_ShipToAccount": [],
        "ARD_OPS_Carrier": [],
        "ARD_OPS_ProductionMix": [],
        "ARD_OPS_MaintenanceType": [],
        "ARD_OPS_CleaningType": [],
        "ARD_OPS_PackLine": [],
        "ARD_OPS_Bin": [],
        "ARD_OPS_PackRun": [],
        "ARD_OPS_MillRun": [],
        "ARD_OPS_SalesOrder": [],
        "ARD_OPS_SalesOrderLine": [],
        "ARD_OPS_WorkOrder": [],
        "ARD_OPS_BinCleaningLog": [],
        "ARD_OPS_FillOrder": [],
    }
    current_tables = {
        "ARD_OPS_Site": pd.DataFrame(columns=["site_id"]),
        "ARD_OPS_ItemClass": pd.DataFrame(columns=["item_class_id", "item_class_desc"]),
        "ARD_OPS_Product": pd.DataFrame(columns=["product_pk", "product_id", "product_desc", "item_class_id"]),
        "ARD_OPS_Customer": pd.DataFrame([{"customer_id": 3094, "customer_nm": "ORLANDO FOODS INC4198"}]),
        "ARD_OPS_ShipToAccount": pd.DataFrame(columns=["ship_to_id"]),
        "ARD_OPS_Carrier": pd.DataFrame(columns=["carrier_id", "carrier_code"]),
        "ARD_OPS_ProductionMix": pd.DataFrame(columns=["production_mix_id", "production_mix_code"]),
        "ARD_OPS_MaintenanceType": pd.DataFrame(columns=["maintenance_type_id", "maintenance_type"]),
        "ARD_OPS_CleaningType": pd.DataFrame(columns=["cleaning_type_pk", "cleaning_type_id"]),
        "ARD_OPS_PackLine": pd.DataFrame(columns=["line_id", "site_id", "line_name"]),
        "ARD_OPS_Bin": pd.DataFrame(columns=["bin_pk", "bin_id"]),
        "ARD_OPS_PackRun": pd.DataFrame(columns=["pack_run_id"]),
        "ARD_OPS_MillRun": pd.DataFrame(columns=["mill_run_id"]),
        "ARD_OPS_SalesOrder": pd.DataFrame(columns=["order_id", "order_no"]),
        "ARD_OPS_SalesOrderLine": pd.DataFrame(columns=["order_line_id", "order_no"]),
        "ARD_OPS_WorkOrder": pd.DataFrame(columns=["workorder_pk", "wo_no"]),
        "ARD_OPS_BinCleaningLog": pd.DataFrame(columns=["cleaning_log_id"]),
        "ARD_OPS_FillOrder": pd.DataFrame(columns=["fill_order_id"]),
    }

    summary_df, changes_df = build_change_report(previous_snapshot, current_tables)

    customer_summary = summary_df[summary_df["table_name"] == "ARD_OPS_Customer"].iloc[0]
    customer_changes = changes_df[changes_df["table_name"] == "ARD_OPS_Customer"]

    assert customer_summary["updated_records"] == 1
    assert customer_summary["inserted_records"] == 0
    assert customer_summary["deleted_records"] == 0
    assert set(customer_changes["change_type"]) == {"UPDATE"}
    assert customer_changes["column_name"].tolist() == ["customer_nm"]
    assert customer_changes["old_value"].tolist() == ["ORLANDO FOODS INC4199"]
    assert customer_changes["new_value"].tolist() == ["ORLANDO FOODS INC4198"]


def test_write_change_audit_workbook_falls_back_when_target_is_locked(monkeypatch, tmp_path):
    calls = []

    class DummyWriter:
        def __init__(self, path, engine=None):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError("locked file")
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("utils.change_tracker.pd.ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda self, writer, sheet_name=None, index=None: None)

    output_path = tmp_path / "Ardent_Mills_ETL_Change_Audit.xlsx"
    result = write_change_audit_workbook(
        output_path,
        pd.DataFrame([{"table_name": "ARD_OPS_Customer"}]),
        pd.DataFrame(),
    )

    assert len(calls) == 2
    assert calls[0] == output_path
    assert result != output_path
    assert result.name.startswith("Ardent_Mills_ETL_Change_Audit_")
    assert result.suffix == ".xlsx"
