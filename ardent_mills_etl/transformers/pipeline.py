"""
transformers/pipeline.py
─────────────────────────
Orchestrates all transformers in dependency order and returns the
complete tables/issues/details dictionaries consumed by loaders and
validation utilities.
"""

import pandas as pd

from config.table_specs import LOAD_ORDER
from transformers.dimensions import (
    build_bin,
    build_carrier,
    build_cleaning_type,
    build_customer,
    build_item_class,
    build_maintenance_type,
    build_pack_line,
    build_product,
    build_production_mix,
    build_ship_to,
    build_site,
)
from transformers.facts import (
    build_bin_cleaning_log,
    build_fill_order,
    build_mill_run,
    build_pack_run,
    build_sales_order,
    build_work_order,
)


def build_all_tables(
    raw: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, list[dict]], dict[str, pd.DataFrame]]:
    """
    Run every transformer in FK-safe load order.

    Returns:
        tables  – dict[table_name, DataFrame]
        issues  – dict[table_name, list[issue_dict]]
        details – dict[table_name, DataFrame]
    """
    built_tables: dict[str, pd.DataFrame] = {}
    built_issues: dict[str, list[dict]] = {}
    built_details: dict[str, pd.DataFrame] = {}

    # ── Dimension layer ────────────────────────────────────────────────────────
    built_tables["ARD_OPS_Site"],           built_issues["ARD_OPS_Site"],           built_details["ARD_OPS_Site"]           = build_site(raw)
    built_tables["ARD_OPS_ItemClass"],      built_issues["ARD_OPS_ItemClass"],      built_details["ARD_OPS_ItemClass"]      = build_item_class(raw)
    built_tables["ARD_OPS_Product"],        built_issues["ARD_OPS_Product"],        built_details["ARD_OPS_Product"]        = build_product(raw, built_tables["ARD_OPS_ItemClass"])
    built_tables["ARD_OPS_Customer"],       built_issues["ARD_OPS_Customer"],       built_details["ARD_OPS_Customer"]       = build_customer(raw)
    built_tables["ARD_OPS_ShipToAccount"],  built_issues["ARD_OPS_ShipToAccount"],  built_details["ARD_OPS_ShipToAccount"]  = build_ship_to(raw)
    built_tables["ARD_OPS_Carrier"],        built_issues["ARD_OPS_Carrier"],        built_details["ARD_OPS_Carrier"]        = build_carrier(raw)
    built_tables["ARD_OPS_ProductionMix"],  built_issues["ARD_OPS_ProductionMix"],  built_details["ARD_OPS_ProductionMix"]  = build_production_mix(raw)
    built_tables["ARD_OPS_MaintenanceType"],built_issues["ARD_OPS_MaintenanceType"],built_details["ARD_OPS_MaintenanceType"]= build_maintenance_type(raw)
    built_tables["ARD_OPS_CleaningType"],   built_issues["ARD_OPS_CleaningType"],   built_details["ARD_OPS_CleaningType"]   = build_cleaning_type(raw)
    built_tables["ARD_OPS_PackLine"],       built_issues["ARD_OPS_PackLine"],       built_details["ARD_OPS_PackLine"]       = build_pack_line(raw, built_tables["ARD_OPS_Site"])
    built_tables["ARD_OPS_Bin"],            built_issues["ARD_OPS_Bin"],            built_details["ARD_OPS_Bin"]            = build_bin(raw)

    # ── product lookup set for FK resolution ──────────────────────────────────
    product_lookup: set[str] = set(built_tables["ARD_OPS_Product"]["product_id"].dropna().tolist())

    # ── Fact / transaction layer ───────────────────────────────────────────────
    built_tables["ARD_OPS_PackRun"],        built_issues["ARD_OPS_PackRun"],        built_details["ARD_OPS_PackRun"]        = build_pack_run(raw, built_tables["ARD_OPS_Site"], built_tables["ARD_OPS_PackLine"], product_lookup)
    built_tables["ARD_OPS_MillRun"],        built_issues["ARD_OPS_MillRun"],        built_details["ARD_OPS_MillRun"]        = build_mill_run(raw, built_tables["ARD_OPS_ProductionMix"])

    sales_order, sales_line, sales_issues, sales_details = build_sales_order(raw, built_tables["ARD_OPS_Customer"], product_lookup)
    built_tables["ARD_OPS_SalesOrder"]      = sales_order
    built_tables["ARD_OPS_SalesOrderLine"]  = sales_line
    built_issues["ARD_OPS_SalesOrder"]      = sales_issues
    built_issues["ARD_OPS_SalesOrderLine"]  = []
    built_details["ARD_OPS_SalesOrder"]     = sales_details
    built_details["ARD_OPS_SalesOrderLine"] = pd.DataFrame()

    built_tables["ARD_OPS_WorkOrder"],      built_issues["ARD_OPS_WorkOrder"],      built_details["ARD_OPS_WorkOrder"]      = build_work_order(raw, built_tables["ARD_OPS_MaintenanceType"])
    built_tables["ARD_OPS_BinCleaningLog"], built_issues["ARD_OPS_BinCleaningLog"], built_details["ARD_OPS_BinCleaningLog"] = build_bin_cleaning_log(raw, built_tables["ARD_OPS_CleaningType"])
    built_tables["ARD_OPS_FillOrder"],      built_issues["ARD_OPS_FillOrder"],      built_details["ARD_OPS_FillOrder"]      = build_fill_order(raw, built_tables["ARD_OPS_ShipToAccount"], built_tables["ARD_OPS_Carrier"], product_lookup)

    tables = {table_name: built_tables[table_name] for table_name in LOAD_ORDER}
    issues = {table_name: built_issues.get(table_name, []) for table_name in LOAD_ORDER}
    details = {
        table_name: built_details.get(table_name, pd.DataFrame())
        for table_name in LOAD_ORDER
    }
    return tables, issues, details
