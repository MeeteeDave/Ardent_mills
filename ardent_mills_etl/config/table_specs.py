"""
config/table_specs.py
─────────────────────
Single source of truth for every target table:
  - source sheet(s)
  - business key
  - loader key (used for MERGE ON clause)
  - count validation rule
  - grain description
  - physical Oracle table name (when it differs from the logical name)

Load order respects FK dependencies (dimensions before facts).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    source_sheet: str
    business_key: list[str]
    count_rule: str
    grain_description: str
    loader_key: list[str]
    physical_table_name: str | None = None


TABLE_SPECS: dict[str, TableSpec] = {
    # ── Dimension tables (no FK dependencies) ─────────────────────────────────
    "ARD_OPS_Site": TableSpec(
        "BinCleaning", ["site_id"], "unique_business_key",
        "One row per site_id.", ["site_id"]
    ),
    "ARD_OPS_ItemClass": TableSpec(
        "Sales", ["item_class_id"], "unique_business_key",
        "One row per item class.", ["item_class_id"]
    ),
    "ARD_OPS_Product": TableSpec(
        "Sales/Fills", ["product_id"], "unique_business_key",
        "One row per product.", ["product_id"]
    ),
    "ARD_OPS_Customer": TableSpec(
        "Sales", ["customer_id"], "unique_business_key",
        "One row per customer.", ["customer_id"]
    ),
    "ARD_OPS_ShipToAccount": TableSpec(
        "Fills", ["ship_to_id"], "unique_business_key",
        "One row per ship-to account.", ["ship_to_id"]
    ),
    "ARD_OPS_Carrier": TableSpec(
        "Fills", ["carrier_id"], "unique_business_key",
        "One row per carrier.", ["carrier_id"]
    ),
    "ARD_OPS_ProductionMix": TableSpec(
        "Mill", ["production_mix_id"], "unique_business_key",
        "One row per production mix code.", ["production_mix_id"]
    ),
    "ARD_OPS_MaintenanceType": TableSpec(
        "WorkOrder", ["maintenance_type_id"], "unique_business_key",
        "One row per maintenance type.", ["maintenance_type"]
    ),
    "ARD_OPS_CleaningType": TableSpec(
        "BinCleaning", ["cleaning_type_id"], "unique_business_key",
        "One row per cleaning type.", ["cleaning_type_id"]
    ),
    "ARD_OPS_PackLine": TableSpec(
        "Pack", ["line_id"], "unique_business_key",
        "One row per site and line.", ["line_id"]
    ),
    "ARD_OPS_Bin": TableSpec(
        "BinCleaning", ["bin_id"], "unique_business_key",
        "One row per bin.", ["bin_id"]
    ),
    # ── Fact / transaction tables ──────────────────────────────────────────────
    "ARD_OPS_PackRun": TableSpec(
        "Pack", ["pack_run_id"], "same_as_source",
        "One row per source pack record.", ["pack_run_id"]
    ),
    "ARD_OPS_MillRun": TableSpec(
        "Mill", ["mill_run_id"], "same_as_source",
        "One row per source mill record.", ["mill_run_id"]
    ),
    "ARD_OPS_SalesOrder": TableSpec(
        "Sales", ["order_no"], "unique_order_header",
        "One row per order header.", ["order_no"]
    ),
    "ARD_OPS_SalesOrderLine": TableSpec(
        "Sales", ["order_line_id"], "same_as_source",
        "One row per source sales line.", ["order_line_id"]
    ),
    "ARD_OPS_WorkOrder": TableSpec(
        "WorkOrder", ["wo_no"], "same_as_source",
        "One row per work order.", ["wo_no"],
        physical_table_name="ARD_OPS_WORKORDER"
    ),
    "ARD_OPS_BinCleaningLog": TableSpec(
        "BinCleaning", ["cleaning_log_id"], "same_as_source",
        "One row per source bin-cleaning log.", ["cleaning_log_id"]
    ),
    "ARD_OPS_FillOrder": TableSpec(
        "Fills", ["fill_order_id"], "same_as_source",
        "One row per source fill record.", ["fill_order_id"]
    ),
}

# Load order respects FK dependencies.
# Keep this explicit so table execution order does not accidentally change if
# TABLE_SPECS is rearranged for readability or new tables are inserted.
LOAD_ORDER: list[str] = [
    "ARD_OPS_Site",
    "ARD_OPS_ItemClass",
    "ARD_OPS_Product",
    "ARD_OPS_Customer",
    "ARD_OPS_ShipToAccount",
    "ARD_OPS_Carrier",
    "ARD_OPS_ProductionMix",
    "ARD_OPS_MaintenanceType",
    "ARD_OPS_CleaningType",
    "ARD_OPS_PackLine",
    "ARD_OPS_Bin",
    "ARD_OPS_PackRun",
    "ARD_OPS_MillRun",
    "ARD_OPS_SalesOrder",
    "ARD_OPS_SalesOrderLine",
    "ARD_OPS_WorkOrder",
    "ARD_OPS_BinCleaningLog",
    "ARD_OPS_FillOrder",
]
