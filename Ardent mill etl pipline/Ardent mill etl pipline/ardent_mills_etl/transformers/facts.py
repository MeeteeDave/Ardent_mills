"""
transformers/facts.py
──────────────────────
One function per fact / transaction table.
Each function returns (DataFrame, issues_list, details_DataFrame).

Duplicate-prevention strategy
──────────────────────────────
Fact builders preserve existing primary keys from the last snapshot by
business key and assign new primary keys at the end. Each builder also calls
drop_duplicates on its business key before returning so the Oracle MERGE
never sees collisions.
"""

import pandas as pd

from config.settings import UNKNOWN_TEXT
from utils.helpers import (
    add_audit,
    assign_preserved_ids,
    normalize_text,
    normalize_upper,
    parse_site_short_name,
)


# ── ARD_OPS_PackRun ───────────────────────────────────────────────────────────

def build_pack_run(
    raw: dict[str, pd.DataFrame],
    site_df: pd.DataFrame,
    pack_line_df: pd.DataFrame,
    product_lookup: set[str],
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    pack = raw["Pack"].copy()
    site_bits = parse_site_short_name(pack["SITE_SHORT_NAME"])
    pack["site_id"] = site_bits["site_id"]
    pack["product_id"] = pack["PRODUCT"].apply(normalize_text)
    unmapped_mask = ~pack["product_id"].isin(product_lookup) & pack["product_id"].notna()
    pack["line_name"] = pack["LINE"].apply(normalize_upper)

    line_map = (
        pack_line_df
        .assign(_key=pack_line_df["site_id"].astype(str) + "|" + pack_line_df["line_name"].astype(str))
        .set_index("_key")["line_id"]
        .to_dict()
    )
    pack["_line_key"] = pack["site_id"].astype(str) + "|" + pack["line_name"].astype(str)
    pack["line_id"] = pack["_line_key"].map(line_map).astype("Int64")
    pack["pack_date"] = pd.to_datetime(pack["PACKDATE"], errors="coerce")
    pack["good_units"] = pd.to_numeric(pack["GoodUnits"], errors="coerce")
    pack["target_units"] = pd.to_numeric(pack["TargetUnits"], errors="coerce")
    pack["total_units"] = pd.to_numeric(pack["TotalUnits"], errors="coerce").astype("Int64")
    pack["calc_dt"] = pd.to_numeric(pack["CalcDT"], errors="coerce")
    pack["minutes_run"] = pd.to_numeric(pack["MinutesRun"], errors="coerce")
    pack["pack_oee"] = pd.to_numeric(pack["Pack OEE"], errors="coerce")
    pack.loc[unmapped_mask, "product_id"] = None
    pack = pack.sort_values("_source_row_num").reset_index(drop=True)
    pack = assign_preserved_ids(
        pack,
        "ARD_OPS_PackRun",
        "pack_run_id",
        ["site_id", "product_id", "line_id", "pack_date", "good_units", "target_units", "total_units", "calc_dt", "minutes_run", "pack_oee"],
        23000,
        include_occurrence=True,
    )

    issues = []
    if pack["line_id"].isna().sum():
        issues.append(
            {
                "target_table": "ARD_OPS_PackRun",
                "source_sheet": "Pack",
                "issue_type": "Missing line lookup",
                "impacted_rows": int(pack["line_id"].isna().sum()),
                "reason": "Pack rows with an unmapped site_id and line_name cannot resolve a line_id.",
                "resolution": "Review SITE_SHORT_NAME and LINE values in source data.",
            }
        )
    if pack["product_id"].isna().sum():
        issues.append(
            {
                "target_table": "ARD_OPS_PackRun",
                "source_sheet": "Pack",
                "issue_type": "Missing product lookup",
                "impacted_rows": int(pack["product_id"].isna().sum()),
                "reason": "Pack rows with a product code not found in the product dimension.",
                "resolution": "Review PRODUCT values in the Pack sheet.",
            }
        )
    missing_products = int(unmapped_mask.sum())
    if missing_products:
        issues.append(
            {
                "target_table": "ARD_OPS_PackRun",
                "source_sheet": "Pack",
                "issue_type": "Unmapped product id",
                "impacted_rows": missing_products,
                "reason": "Some Pack PRODUCT values do not exist in the product dimension.",
                "resolution": "Those pack-only codes are set to NULL in PackRun.",
            }
        )

    out = add_audit(
        pack[["pack_run_id", "site_id", "product_id", "line_id", "pack_date",
              "good_units", "target_units", "total_units", "calc_dt", "minutes_run", "pack_oee"]]
    )
    return out, issues, pd.DataFrame()


# ── ARD_OPS_MillRun ───────────────────────────────────────────────────────────

def build_mill_run(
    raw: dict[str, pd.DataFrame], production_mix_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    mill = raw["Mill"].copy()
    site_bits = parse_site_short_name(mill["SITE_SHORT_NAME"])
    mill["site_id"] = site_bits["site_id"]
    mix_map = production_mix_df.set_index("production_mix_code")["production_mix_id"].to_dict()
    mill["production_mix_code"] = mill["ProductionMix"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    mill["production_mix_id"] = mill["production_mix_code"].map(mix_map).astype("Int64")
    mill["mill_date"] = pd.to_datetime(mill["MILLDATE"], errors="coerce")
    mill["unit"] = mill["UNIT"].apply(normalize_text)
    mill["calc_downtime"] = pd.to_numeric(mill["Calculated Downtime"], errors="coerce")
    mill["min_run"] = pd.to_numeric(mill["MinRun"], errors="coerce")
    mill["no_demand_downtime"] = pd.to_numeric(mill["NODemand Downtime"], errors="coerce")
    mill["mill_oee"] = pd.to_numeric(mill["Mill OEE"], errors="coerce")
    mill = mill.sort_values("_source_row_num").reset_index(drop=True)
    mill = assign_preserved_ids(
        mill,
        "ARD_OPS_MillRun",
        "mill_run_id",
        ["site_id", "mill_date", "unit", "production_mix_id", "calc_downtime", "min_run", "no_demand_downtime", "mill_oee"],
        26000,
        include_occurrence=True,
    )

    out = add_audit(
        mill[["mill_run_id", "site_id", "mill_date", "unit", "production_mix_id",
              "calc_downtime", "min_run", "no_demand_downtime", "mill_oee"]]
    )
    return out, [], pd.DataFrame()


# ── ARD_OPS_SalesOrder + ARD_OPS_SalesOrderLine ───────────────────────────────

def build_sales_order(
    raw: dict[str, pd.DataFrame],
    customer_df: pd.DataFrame,
    product_lookup: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict], pd.DataFrame]:
    sales = raw["Sales"].copy()
    site_bits = parse_site_short_name(sales["SITE_SHORT_NAME"])
    sales["site_id"] = site_bits["site_id"]
    cust_map = customer_df.set_index("customer_nm")["customer_id"].to_dict()
    sales["customer_nm"] = sales["CUSTOMER_NM"].apply(normalize_text)
    sales["customer_id"] = sales["customer_nm"].map(cust_map).astype("Int64")
    sales["order_no"] = sales["ORDER_NO"].apply(normalize_text)
    sales["product_id"] = sales["ITEM_NUM"].apply(normalize_text)
    sales["ship_date"] = pd.to_datetime(sales["SHIP_DATE"], errors="coerce")
    sales["order_status"] = sales["ORDER_STATUS_INDICATOR"].apply(normalize_text)
    sales["invoice_cwts"] = pd.to_numeric(sales["INVOICE_CWTS"], errors="coerce")

    # Header: one row per order_no (duplicate guard built-in via drop_duplicates)
    order_df = (
        sales[["order_no", "site_id", "customer_id", "ship_date", "order_status"]]
        .drop_duplicates(subset=["order_no"])
        .sort_values("order_no")
        .reset_index(drop=True)
    )
    order_df = assign_preserved_ids(order_df, "ARD_OPS_SalesOrder", "order_id", ["order_no"], 45000)
    order_df = add_audit(order_df)

    # Line: one row per source row
    line_df = sales[["_source_row_num", "order_no", "product_id", "invoice_cwts"]].copy()
    line_df = line_df.sort_values("_source_row_num").reset_index(drop=True)
    line_df = assign_preserved_ids(
        line_df,
        "ARD_OPS_SalesOrderLine",
        "order_line_id",
        ["order_no", "product_id", "invoice_cwts"],
        30000,
        include_occurrence=True,
    )
    line_df = add_audit(line_df[["order_line_id", "order_no", "product_id", "invoice_cwts"]])

    issues = [
        {
            "target_table": "ARD_OPS_SalesOrder",
            "source_sheet": "Sales",
            "issue_type": "Header rows collapsed from detail",
            "impacted_rows": int(len(sales) - len(order_df)),
            "reason": "SalesOrder is a header table; multiple lines with the same ORDER_NO become one header.",
            "resolution": "Expected OLTP normalization behavior.",
        }
    ]
    return order_df, line_df, issues, pd.DataFrame()


# ── ARD_OPS_WorkOrder ─────────────────────────────────────────────────────────

def build_work_order(
    raw: dict[str, pd.DataFrame], maintenance_type_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    work = raw["WorkOrder"].copy()
    site_bits = parse_site_short_name(work["SITE_SHORT_NAME"])
    work["site_id"] = site_bits["site_id"]
    mt_map = maintenance_type_df.set_index("maintenance_type")["maintenance_type_id"].to_dict()
    work["maintenance_type"] = work["MAINTENANCE_TYP"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    work["maintenance_type_id"] = work["maintenance_type"].map(mt_map).astype("Int64")
    work["wo_no"] = work["WO_NO"].apply(normalize_text)
    work["category_cd"] = work["CATEGORY_CD"].apply(normalize_text)
    work["status_cd"] = work["STATUS_CD"].apply(normalize_text)
    work["preventive_corrective_ind"] = work["PREVENTIVE_CORRECTIVE_IND"].apply(normalize_text)
    work["late_indicator"] = work["LATE_INDICATOR"].apply(normalize_text)
    work["required_date"] = pd.to_datetime(work["REQUIRED_DATE"], errors="coerce")
    for col in ["WO_COUNT", "WO_LATE_COUNT", "WO_ONTIME_COUNT", "WO_UPCOMING_COUNT"]:
        work[col] = pd.to_numeric(work[col], errors="coerce").astype("Int64")

    out = work[
        ["wo_no", "site_id", "maintenance_type_id", "category_cd", "status_cd",
         "preventive_corrective_ind", "late_indicator", "required_date",
         "WO_COUNT", "WO_LATE_COUNT", "WO_ONTIME_COUNT", "WO_UPCOMING_COUNT"]
    ].rename(
        columns={
            "WO_COUNT": "wo_count",
            "WO_LATE_COUNT": "wo_late_count",
            "WO_ONTIME_COUNT": "wo_ontime_count",
            "WO_UPCOMING_COUNT": "wo_upcoming_count",
        }
    )
    # ── duplicate guard ──────────────────────────────────────────────────────
    out = out.drop_duplicates(subset=["wo_no"]).sort_values("wo_no").reset_index(drop=True)
    out = assign_preserved_ids(out, "ARD_OPS_WorkOrder", "workorder_pk", ["wo_no"], 48000)
    out = add_audit(out)
    return out, [], pd.DataFrame()


# ── ARD_OPS_BinCleaningLog ────────────────────────────────────────────────────

def build_bin_cleaning_log(
    raw: dict[str, pd.DataFrame], cleaning_type_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    bc = raw["BinCleaning"].copy()
    bc["bin_id"] = bc["Bin_ID"].apply(normalize_text)
    bc["cleaning_type_id"] = bc["CleaningType_ID"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    bc["cleaning_completed_on"] = pd.to_datetime(bc["CleaningCompletedOn"], errors="coerce")
    bc["cleaning_completed_by"] = bc["CleaningCompletedBy"].apply(normalize_text)
    bc["days_since_last_cleaning"] = pd.to_numeric(bc["DaysSinceLastCleaning"], errors="coerce")
    bc["bin_status"] = bc["BinStatus"].apply(normalize_text)
    bc["clean_standard_in_place"] = pd.to_numeric(bc["CleanStandardInPlace"], errors="coerce")
    bc["clean_standard_freq"] = pd.to_numeric(bc["CurrentCleaningStdFrequency"], errors="coerce")
    bc["comments"] = bc["comments"].apply(normalize_text)
    bc["last_refresh_time"] = pd.to_datetime(bc["LastRefreshTime"], errors="coerce")
    bc["status_as_of_date"] = pd.to_datetime(bc["Status_AsOf_Date"], errors="coerce")
    bc["status_as_of_wk_start"] = pd.to_datetime(bc["Status_AsOf_Date_1stofweek"], errors="coerce")
    bc = bc.sort_values("_source_row_num").reset_index(drop=True)
    bc = assign_preserved_ids(
        bc,
        "ARD_OPS_BinCleaningLog",
        "cleaning_log_id",
        ["bin_id", "cleaning_type_id", "cleaning_completed_on", "cleaning_completed_by", "status_as_of_date"],
        35000,
        include_occurrence=True,
    )

    out = add_audit(
        bc[["cleaning_log_id", "bin_id", "cleaning_type_id", "cleaning_completed_on",
            "cleaning_completed_by", "days_since_last_cleaning", "bin_status",
            "clean_standard_in_place", "clean_standard_freq", "comments",
            "last_refresh_time", "status_as_of_date", "status_as_of_wk_start"]]
    )
    return out, [], pd.DataFrame()


# ── ARD_OPS_FillOrder ─────────────────────────────────────────────────────────

def build_fill_order(
    raw: dict[str, pd.DataFrame],
    ship_to_df: pd.DataFrame,
    carrier_df: pd.DataFrame,
    product_lookup: set[str],
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    fills = raw["Fills"].copy()
    site_map = {"ALBANY": 1001, "AYER": 1004, "OGDEN": 1025}
    fills["site_id"] = fills["Site_Name"].apply(normalize_upper).map(site_map).astype("Int64")
    carrier_map = carrier_df.set_index("carrier_code")["carrier_id"].to_dict()
    fills["carrier_code"] = fills["Carrier_ID"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    fills["carrier_id"] = fills["carrier_code"].map(carrier_map).astype("Int64")
    fills["product_id"] = fills["Product"].apply(normalize_text)
    fills["order_number"] = pd.to_numeric(fills["OrderNumber"], errors="coerce").astype("Int64")
    fills["vessel_id"] = pd.to_numeric(fills["Vessel_ID"], errors="coerce").astype("Int64")
    fills["ship_to_id"] = pd.to_numeric(fills["ShipTo"], errors="coerce").astype("Int64")
    fills["bulk_or_sack"] = fills["BulkOrSack"].apply(normalize_text)
    fills["miles"] = pd.to_numeric(fills["Miles"], errors="coerce").astype("Int64")
    fills["drop_ship"] = fills["Drop_Ship"].apply(normalize_text)
    fills["modifier"] = fills["modifier"].apply(normalize_text)
    fills["delivery_note_no"] = pd.to_numeric(fills["DeliveryNoteNo"], errors="coerce").astype("Int64")
    fills["load_date"] = pd.to_datetime(fills["Load_Date"], errors="coerce")
    fills["ship_date"] = pd.to_datetime(fills["Ship_Date"], errors="coerce")
    fills["released_date"] = pd.to_datetime(fills["Released_Date"], errors="coerce")

    for col in ["ShippedCwt", "Volume", "exceptioncwts", "Baseline",
                "MaxForLoad", "GoalForLoad", "VAR_to_Goal",
                "VAR_to_Baseline", "VAR_to_LoadMax", "VAR_to_SiteMax"]:
        fills[col] = pd.to_numeric(fills[col], errors="coerce")

    for col in ["SiteGoaL", "SiteMax", "MadeGoal"]:
        fills[col] = pd.to_numeric(fills[col], errors="coerce").astype("Int64")

    fills["excluded"] = fills["Excluded"].apply(normalize_text)
    fills["exception_flag"] = fills["Exception_flag"].apply(normalize_text)
    fills = fills.sort_values("_source_row_num").reset_index(drop=True)
    fills = assign_preserved_ids(
        fills,
        "ARD_OPS_FillOrder",
        "fill_order_id",
        ["order_number", "vessel_id", "site_id", "ship_to_id", "carrier_id", "product_id", "delivery_note_no", "load_date", "ship_date"],
        38000,
        include_occurrence=True,
    )

    out = add_audit(
        fills[
            ["fill_order_id", "order_number", "vessel_id", "site_id", "ship_to_id",
             "carrier_id", "product_id", "bulk_or_sack", "miles", "drop_ship",
             "modifier", "delivery_note_no", "load_date", "ship_date", "released_date",
             "ShippedCwt", "Volume", "SiteGoaL", "SiteMax", "exceptioncwts",
             "Baseline", "MaxForLoad", "GoalForLoad", "MadeGoal",
             "VAR_to_Goal", "VAR_to_Baseline", "VAR_to_LoadMax", "VAR_to_SiteMax",
             "excluded", "exception_flag"]
        ].rename(
            columns={
                "ShippedCwt": "shipped_cwt",
                "Volume": "volume",
                "SiteGoaL": "site_goal",
                "SiteMax": "site_max",
                "exceptioncwts": "exception_cwts",
                "Baseline": "baseline",
                "MaxForLoad": "max_for_load",
                "GoalForLoad": "goal_for_load",
                "MadeGoal": "made_goal",
                "VAR_to_Goal": "var_to_goal",
                "VAR_to_Baseline": "var_to_baseline",
                "VAR_to_LoadMax": "var_to_load_max",
                "VAR_to_SiteMax": "var_to_site_max",
            }
        )
    )
    return out, [], pd.DataFrame()
