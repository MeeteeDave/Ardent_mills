"""
transformers/dimensions.py
───────────────────────────
One function per dimension table.
Each function returns (DataFrame, issues_list, details_DataFrame).

Duplicate-prevention strategy
──────────────────────────────
Every dimension builder calls .drop_duplicates(subset=[business_key])
before returning so the Oracle MERGE never receives two rows that would
collide on the ON clause.
"""

import re

import pandas as pd

from config.settings import UNKNOWN_TEXT
from utils.helpers import (
    add_audit,
    add_unknown_dimension_row,
    assign_preserved_ids,
    normalize_text,
    normalize_upper,
    parse_site_short_name,
)


# ── ARD_OPS_Site ───────────────────────────────────────────────────────────────

def build_site(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    issue_rows: list[dict] = []

    parsed_frames = []
    for sheet in ["Pack", "Mill", "Sales", "WorkOrder"]:
        parsed = parse_site_short_name(raw[sheet]["SITE_SHORT_NAME"])
        parsed["ops_type"] = None
        parsed["region"] = None
        parsed["pack_plant"] = None
        parsed["company"] = None
        parsed["country_cd"] = None
        parsed["source_sheet"] = sheet
        parsed_frames.append(parsed)

    bin_sites = raw["BinCleaning"][
        ["SHORTPLANTNAME", "SITE_ID_OPS", "OPS_TYPE", "REGION", "PACKPLANT", "COMPANY", "COUNTRY_CD"]
    ].copy()
    bin_sites = bin_sites.rename(
        columns={
            "SHORTPLANTNAME": "site_name",
            "SITE_ID_OPS": "site_id",
            "OPS_TYPE": "ops_type",
            "REGION": "region",
            "PACKPLANT": "pack_plant",
            "COMPANY": "company",
            "COUNTRY_CD": "country_cd",
        }
    )
    bin_sites["site_id"] = pd.to_numeric(bin_sites["site_id"], errors="coerce").astype("Int64")
    bin_sites["source_sheet"] = "BinCleaning"
    parsed_frames.append(bin_sites)

    combined = pd.concat(parsed_frames, ignore_index=True)
    before = len(combined)
    combined = combined.dropna(subset=["site_id"]).copy()
    combined["site_name"] = combined["site_name"].apply(normalize_text)
    combined = combined.sort_values(by=["site_id", "source_sheet"]).reset_index(drop=True)

    final_rows = []
    for site_id, grp in combined.groupby("site_id", dropna=False):
        site_name = grp["site_name"].dropna().iloc[0] if grp["site_name"].dropna().any() else None
        best = grp[grp["source_sheet"] == "BinCleaning"]
        row = (best.iloc[0] if not best.empty else grp.iloc[0]).to_dict()
        row["site_name"] = site_name
        final_rows.append(row)

    site_df = pd.DataFrame(final_rows)[
        ["site_id", "site_name", "ops_type", "region", "pack_plant", "company", "country_cd"]
    ]
    # ── duplicate guard ──────────────────────────────────────────────────────
    site_df = site_df.drop_duplicates(subset=["site_id"]).sort_values("site_id").reset_index(drop=True)
    site_df = add_audit(site_df)

    duplicate_rows = before - site_df.shape[0]
    if duplicate_rows:
        issue_rows.append(
            {
                "target_table": "ARD_OPS_Site",
                "source_sheet": "Multiple",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": duplicate_rows,
                "reason": "The target site dimension stores one row per site_id.",
                "resolution": "Expected dimension behavior.",
            }
        )

    return site_df, issue_rows, pd.DataFrame()


# ── ARD_OPS_ItemClass ─────────────────────────────────────────────────────────

def build_item_class(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    issues: list[dict] = []
    sales = raw["Sales"][["ITEM_CLASS_DESC"]].copy()
    sales["item_class_desc"] = sales["ITEM_CLASS_DESC"].apply(normalize_text)
    df = sales[["item_class_desc"]].drop_duplicates().reset_index(drop=True)
    df = df.dropna(subset=["item_class_desc"]).copy()
    df = df.sort_values("item_class_desc").reset_index(drop=True)
    df = assign_preserved_ids(df, "ARD_OPS_ItemClass", "item_class_id", ["item_class_desc"], 1)

    duplicate_rows = len(sales) - sales["item_class_desc"].dropna().nunique()
    if duplicate_rows:
        issues.append(
            {
                "target_table": "ARD_OPS_ItemClass",
                "source_sheet": "Sales",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": duplicate_rows,
                "reason": "The target dimension stores one row per unique item class description.",
                "resolution": "Expected dimension behavior.",
            }
        )

    # ── duplicate guard ──────────────────────────────────────────────────────
    df = df.drop_duplicates(subset=["item_class_id"])
    df = add_audit(df[["item_class_id", "item_class_desc"]].sort_values("item_class_id").reset_index(drop=True))
    return df, issues, pd.DataFrame()


# ── ARD_OPS_Product ───────────────────────────────────────────────────────────

def build_product(
    raw: dict[str, pd.DataFrame], item_class_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    issues: list[dict] = []

    # Sales
    sales = raw["Sales"][["ITEM_NUM", "ITEM_DESC", "ITEM_CLASS_DESC"]].copy()
    sales["product_id"] = sales["ITEM_NUM"].apply(normalize_text)
    sales["product_desc"] = sales["ITEM_DESC"].apply(normalize_text)
    sales["item_class_desc"] = sales["ITEM_CLASS_DESC"].apply(normalize_text)
    sales["source_sheet"] = "Sales"

    # Fills
    fills = raw["Fills"][["Product", "Product_Desc"]].copy()
    fills["product_id"] = fills["Product"].apply(normalize_text)
    fills["product_desc"] = fills["Product_Desc"].apply(normalize_text)
    fills["item_class_desc"] = None
    fills["source_sheet"] = "Fills"

    combined = pd.concat(
        [
            sales[["source_sheet", "product_id", "product_desc", "item_class_desc"]],
            fills[["source_sheet", "product_id", "product_desc", "item_class_desc"]],
        ],
        ignore_index=True,
    )

    # Normalize keys
    combined["product_id"] = combined["product_id"].astype(str).str.strip().str.upper()

    null_products = combined["product_id"].isna().sum()
    combined = combined.dropna(subset=["product_id"]).copy()
    combined = combined.sort_values(by=["product_id", "source_sheet"]).reset_index(drop=True)

    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = combined.drop_duplicates(subset=["product_id"], keep="first").copy()

    # Map item class
    item_class_map = item_class_df.set_index("item_class_desc")["item_class_id"].to_dict()
    deduped["item_class_id"] = deduped["item_class_desc"].map(item_class_map).astype("Int64")

    fills_only_missing = deduped["item_class_desc"].isna().sum()
    if fills_only_missing:
        issues.append(
            {
                "target_table": "ARD_OPS_Product",
                "source_sheet": "Fills",
                "issue_type": "Missing item class left null",
                "impacted_rows": int(fills_only_missing),
                "reason": "Fills products do not include ITEM_CLASS_DESC.",
                "resolution": "item_class_id left null.",
            }
        )

    duplicate_rows = len(combined) - len(deduped)
    if duplicate_rows:
        issues.append(
            {
                "target_table": "ARD_OPS_Product",
                "source_sheet": "Sales/Fills",
                "issue_type": "Duplicate collapsed",
                "impacted_rows": duplicate_rows,
                "reason": "One row per product_id.",
                "resolution": "Expected behavior.",
            }
        )

    if null_products:
        issues.append(
            {
                "target_table": "ARD_OPS_Product",
                "source_sheet": "Sales/Fills",
                "issue_type": "Null product removed",
                "impacted_rows": int(null_products),
                "reason": "Null product_id not allowed.",
                "resolution": "Check source.",
            }
        )

    out = deduped[["product_id", "product_desc", "item_class_id"]].copy()
    # final safety dedup
    out = out.drop_duplicates(subset=["product_id"])
    out = out.sort_values("product_id").reset_index(drop=True)
    out = assign_preserved_ids(out, "ARD_OPS_Product", "product_pk", ["product_id"], 500)
    out = add_audit(out)
    return out, issues, pd.DataFrame()


# ── ARD_OPS_Customer ──────────────────────────────────────────────────────────

LEGAL_SUFFIX_PATTERN = re.compile(
    r"\b(INC|INCORPORATED|LLC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY)\b\.?",
    re.IGNORECASE,
)


def customer_identity_key(value) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    text = LEGAL_SUFFIX_PATTERN.sub("", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text or None


def build_customer(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """
    Deduplicate by normalized customer identity and preserve IDs across
    common legal-name edits such as adding LTD/INC/LLC.
    """
    sales = raw["Sales"][["CUSTOMER_NM"]].copy()
    sales["customer_nm"] = sales["CUSTOMER_NM"].apply(normalize_text)
    sales["customer_identity_key"] = sales["customer_nm"].apply(customer_identity_key)

    # ── duplicate guard (critical — this is the bug fix) ─────────────────────
    deduped = (
        sales.dropna(subset=["customer_identity_key"])
        .drop_duplicates(subset=["customer_identity_key"], keep="last")
        .copy()
    )
    deduped = deduped.sort_values("customer_nm").reset_index(drop=True)
    deduped = assign_preserved_ids(
        deduped,
        "ARD_OPS_Customer",
        "customer_id",
        ["customer_identity_key"],
        3000,
    )

    issues = []
    duplicate_rows = len(sales) - sales["customer_identity_key"].dropna().nunique()
    if duplicate_rows:
        issues.append(
            {
                "target_table": "ARD_OPS_Customer",
                "source_sheet": "Sales",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": duplicate_rows,
                "reason": "The customer dimension stores one row per normalized customer identity.",
                "resolution": "Expected dimension behavior.",
            }
        )

    # Final guard: also deduplicate on customer_id.
    out = deduped[["customer_id", "customer_nm"]].drop_duplicates(subset=["customer_id"])
    out = add_audit(out.sort_values("customer_nm").reset_index(drop=True))
    return out, issues, pd.DataFrame()


# ── ARD_OPS_ShipToAccount ─────────────────────────────────────────────────────

def build_ship_to(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    fills = raw["Fills"][
        ["ShipTo", "ShipToName", "SoldToName", "ShipTo_CITY", "ShipTo_STATE", "ShipTo_ZIP", "ShipTo_COUNTRY"]
    ].copy()
    fills["ship_to_id"] = pd.to_numeric(fills["ShipTo"], errors="coerce").astype("Int64")
    fills["ship_to_name"] = fills["ShipToName"].apply(normalize_text)
    fills["sold_to_name"] = fills["SoldToName"].apply(normalize_text)
    fills["city"] = fills["ShipTo_CITY"].apply(normalize_text)
    fills["state"] = fills["ShipTo_STATE"].apply(normalize_text)
    fills["zip"] = fills["ShipTo_ZIP"].apply(normalize_text)
    fills["country"] = fills["ShipTo_COUNTRY"].apply(normalize_text)

    null_ids = fills["ship_to_id"].isna().sum()
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = fills.dropna(subset=["ship_to_id"]).drop_duplicates(subset=["ship_to_id"]).copy()

    issues = []
    if null_ids:
        issues.append(
            {
                "target_table": "ARD_OPS_ShipToAccount",
                "source_sheet": "Fills",
                "issue_type": "Null ship-to key removed",
                "impacted_rows": int(null_ids),
                "reason": "A null ShipTo cannot be loaded as a ship-to account.",
                "resolution": "Review source data if these rows are expected.",
            }
        )
    duplicate_rows = len(fills) - len(deduped) - null_ids
    if duplicate_rows > 0:
        issues.append(
            {
                "target_table": "ARD_OPS_ShipToAccount",
                "source_sheet": "Fills",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": int(duplicate_rows),
                "reason": "The ship-to dimension stores one row per ShipTo identifier.",
                "resolution": "Expected dimension behavior.",
            }
        )

    out = add_audit(
        deduped[["ship_to_id", "ship_to_name", "sold_to_name", "city", "state", "zip", "country"]]
    )
    return out, issues, pd.DataFrame()


# ── ARD_OPS_Carrier ───────────────────────────────────────────────────────────

def build_carrier(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    fills = raw["Fills"][["Carrier_ID"]].copy()
    fills["carrier_code"] = fills["Carrier_ID"].apply(normalize_text)
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = fills.drop_duplicates(subset=["carrier_code"]).dropna(subset=["carrier_code"])
    deduped = deduped.sort_values("carrier_code").reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_Carrier", "carrier_id", ["carrier_code"], 11000)

    issues = []
    if fills["carrier_code"].isna().sum():
        deduped = add_unknown_dimension_row(deduped[["carrier_id", "carrier_code"]], "carrier_id", "carrier_code")
        issues.append(
            {
                "target_table": "ARD_OPS_Carrier",
                "source_sheet": "Fills",
                "issue_type": "Unknown member inserted",
                "impacted_rows": int(fills["carrier_code"].isna().sum()),
                "reason": "Some Fills rows have no Carrier_ID; an UNKNOWN member was added.",
                "resolution": "Mapped missing carriers to UNKNOWN.",
            }
        )

    out = add_audit(deduped[["carrier_id", "carrier_code"]])
    return out, issues, pd.DataFrame()


# ── ARD_OPS_ProductionMix ─────────────────────────────────────────────────────

def build_production_mix(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    mill = raw["Mill"][["ProductionMix"]].copy()
    mill["production_mix_code"] = mill["ProductionMix"].apply(normalize_text)
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = mill.drop_duplicates(subset=["production_mix_code"]).dropna(subset=["production_mix_code"])
    deduped = deduped.sort_values("production_mix_code").reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_ProductionMix", "production_mix_id", ["production_mix_code"], 13000)

    if mill["production_mix_code"].isna().sum():
        deduped = add_unknown_dimension_row(
            deduped[["production_mix_id", "production_mix_code"]], "production_mix_id", "production_mix_code"
        )

    out = add_audit(deduped[["production_mix_id", "production_mix_code"]])
    return out, [], pd.DataFrame()


# ── ARD_OPS_MaintenanceType ───────────────────────────────────────────────────

def build_maintenance_type(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    work = raw["WorkOrder"][["_source_row_num", "MAINTENANCE_TYP"]].copy()
    work["maintenance_type"] = work["MAINTENANCE_TYP"].apply(normalize_text)
    null_count = work["maintenance_type"].isna().sum()
    detail_rows = work[work["maintenance_type"].isna()][["_source_row_num"]].copy()
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = work[["maintenance_type"]].fillna(UNKNOWN_TEXT).drop_duplicates().copy()
    deduped = deduped.sort_values("maintenance_type").reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_MaintenanceType", "maintenance_type_id", ["maintenance_type"], 15000)

    issues = []
    if null_count:
        issues.append(
            {
                "target_table": "ARD_OPS_MaintenanceType",
                "source_sheet": "WorkOrder",
                "issue_type": "Null maintenance type mapped to UNKNOWN",
                "impacted_rows": int(null_count),
                "reason": "Some work orders do not have MAINTENANCE_TYP populated.",
                "resolution": "Mapped those rows to the UNKNOWN dimension member.",
            }
        )

    out = add_audit(deduped[["maintenance_type_id", "maintenance_type"]].reset_index(drop=True))

    details = pd.DataFrame()
    if not detail_rows.empty:
        details = detail_rows.assign(
            target_table="ARD_OPS_MaintenanceType",
            source_sheet="WorkOrder",
            reason="Null MAINTENANCE_TYP was mapped to UNKNOWN.",
            source_key=lambda x: "Row " + x["_source_row_num"].astype(str),
            sample_values="MAINTENANCE_TYP = NULL",
        )[["target_table", "source_sheet", "reason", "source_key", "sample_values"]]

    return out, issues, details


# ── ARD_OPS_CleaningType ──────────────────────────────────────────────────────

def build_cleaning_type(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    cleaning = raw["BinCleaning"][
        ["_source_row_num", "CleaningType_ID", "CleaningType", "CurrentCleaningStdFrequency"]
    ].copy()
    cleaning["cleaning_type_id"] = cleaning["CleaningType_ID"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    cleaning["cleaning_type_desc"] = cleaning["CleaningType"].apply(normalize_text).fillna(UNKNOWN_TEXT)
    null_count = (cleaning["CleaningType_ID"].apply(normalize_text).isna()).sum()
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = cleaning.drop_duplicates(subset=["cleaning_type_id"]).copy()
    deduped = deduped.sort_values("cleaning_type_id").reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_CleaningType", "cleaning_type_pk", ["cleaning_type_id"], 17000)

    issues = []
    if null_count:
        issues.append(
            {
                "target_table": "ARD_OPS_CleaningType",
                "source_sheet": "BinCleaning",
                "issue_type": "Null cleaning type mapped to UNKNOWN",
                "impacted_rows": int(null_count),
                "reason": "Some bin-cleaning rows do not have CleaningType_ID populated.",
                "resolution": "Mapped those rows to the UNKNOWN dimension member.",
            }
        )

    out = add_audit(deduped[["cleaning_type_pk", "cleaning_type_id", "cleaning_type_desc"]].reset_index(drop=True))

    details = pd.DataFrame()
    if null_count:
        details = cleaning[cleaning["CleaningType_ID"].apply(normalize_text).isna()][
            ["_source_row_num"]
        ].assign(
            target_table="ARD_OPS_CleaningType",
            source_sheet="BinCleaning",
            reason="Null CleaningType_ID was mapped to UNKNOWN.",
            source_key=lambda x: "Row " + x["_source_row_num"].astype(str),
            sample_values="CleaningType_ID = NULL",
        )[["target_table", "source_sheet", "reason", "source_key", "sample_values"]]

    return out, issues, details


# ── ARD_OPS_PackLine ──────────────────────────────────────────────────────────

def build_pack_line(
    raw: dict[str, pd.DataFrame], site_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    pack = raw["Pack"][["SITE_SHORT_NAME", "LINE"]].copy()
    parsed = parse_site_short_name(pack["SITE_SHORT_NAME"])
    pack["site_id"] = parsed["site_id"]
    pack["line_name"] = pack["LINE"].apply(normalize_upper)
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = pack.drop_duplicates(subset=["site_id", "line_name"]).copy()
    deduped = deduped.sort_values(["site_id", "line_name"]).reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_PackLine", "line_id", ["site_id", "line_name"], 20000)

    issues = []
    duplicate_rows = len(pack) - len(deduped)
    if duplicate_rows:
        issues.append(
            {
                "target_table": "ARD_OPS_PackLine",
                "source_sheet": "Pack",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": int(duplicate_rows),
                "reason": "The target pack-line dimension stores one row per site_id and line_name combination.",
                "resolution": "Expected dimension behavior.",
            }
        )

    out = add_audit(deduped[["line_id", "line_name", "site_id"]].reset_index(drop=True))
    return out, issues, pd.DataFrame()


# ── ARD_OPS_Bin ───────────────────────────────────────────────────────────────

def build_bin(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    bc = raw["BinCleaning"][["Bin_ID", "BinPurpose", "SITE_ID_OPS"]].copy()
    bc["bin_id"] = bc["Bin_ID"].apply(normalize_text)
    bc["bin_purpose"] = bc["BinPurpose"].apply(normalize_text)
    bc["site_id"] = pd.to_numeric(bc["SITE_ID_OPS"], errors="coerce").astype("Int64")
    # ── duplicate guard ──────────────────────────────────────────────────────
    deduped = bc.drop_duplicates(subset=["bin_id"]).dropna(subset=["bin_id"]).copy()
    deduped = deduped.sort_values("bin_id").reset_index(drop=True)
    deduped = assign_preserved_ids(deduped, "ARD_OPS_Bin", "bin_pk", ["bin_id"], 41000)

    issues = []
    duplicate_rows = len(bc) - len(deduped)
    if duplicate_rows:
        issues.append(
            {
                "target_table": "ARD_OPS_Bin",
                "source_sheet": "BinCleaning",
                "issue_type": "Duplicate source grain collapsed",
                "impacted_rows": int(duplicate_rows),
                "reason": "The target bin dimension stores one row per bin_id.",
                "resolution": "Expected dimension behavior.",
            }
        )

    out = add_audit(deduped[["bin_pk", "bin_id", "bin_purpose", "site_id"]].reset_index(drop=True))
    return out, issues, pd.DataFrame()
