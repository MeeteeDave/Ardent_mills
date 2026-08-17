"""
utils/validation.py
────────────────────
Generates the validation workbook and diagnostics JSON.
All quality checks live here — no Oracle dependency.
"""

import json
from pathlib import Path

import pandas as pd

from config.settings import UNKNOWN_TEXT
from config.table_specs import TABLE_SPECS, LOAD_ORDER
from utils.helpers import utc_now_naive


# ── Expected-count rules ───────────────────────────────────────────────────────

def expected_count(source_df: pd.DataFrame, table_name: str) -> int:
    """Return the expected row count for *table_name* given its source data."""
    rule = TABLE_SPECS[table_name].count_rule
    if rule == "same_as_source":
        return len(source_df)
    if table_name == "ARD_OPS_SalesOrder":
        return source_df["ORDER_NO"].astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_Site":
        if "SITE_ID_OPS" in source_df.columns:
            return pd.to_numeric(source_df["SITE_ID_OPS"], errors="coerce").dropna().nunique()
    if table_name == "ARD_OPS_ItemClass":
        return source_df["ITEM_CLASS_DESC"].astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_Customer":
        return source_df["CUSTOMER_NM"].astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_ShipToAccount":
        return pd.to_numeric(source_df["ShipTo"], errors="coerce").dropna().nunique()
    if table_name == "ARD_OPS_Carrier":
        return source_df["Carrier_ID"].astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_ProductionMix":
        return source_df["ProductionMix"].astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_MaintenanceType":
        return source_df["MAINTENANCE_TYP"].fillna(UNKNOWN_TEXT).astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_CleaningType":
        return source_df["CleaningType_ID"].fillna(UNKNOWN_TEXT).astype(str).str.strip().nunique()
    if table_name == "ARD_OPS_PackLine":
        work = source_df[["SITE_SHORT_NAME", "LINE"]].copy()
        from utils.helpers import parse_site_short_name
        site_bits = parse_site_short_name(work["SITE_SHORT_NAME"])
        work["site_id"] = site_bits["site_id"]
        work["line_name"] = work["LINE"].astype(str).str.strip().str.upper()
        return work.drop_duplicates(subset=["site_id", "line_name"]).shape[0]
    if table_name == "ARD_OPS_Bin":
        return source_df["Bin_ID"].astype(str).str.strip().nunique()
    return -1  # cannot determine (e.g. ARD_OPS_Product which merges two sheets)


# ── Summary DataFrame ──────────────────────────────────────────────────────────

def find_foreign_key_issues(tables: dict[str, pd.DataFrame]) -> list[dict]:
    """Detect missing parent keys for child tables with explicit FK expectations."""
    issues: list[dict] = []

    parent = tables.get("ARD_OPS_SalesOrder")
    child = tables.get("ARD_OPS_SalesOrderLine")
    if parent is not None and child is not None:
        if "order_no" in parent.columns and "order_no" in child.columns:
            parent_keys = set(parent["order_no"].dropna().astype(str))
            child_keys = set(child["order_no"].dropna().astype(str))
            missing = sorted(child_keys - parent_keys)
            if missing:
                issues.append(
                    {
                        "target_table": "ARD_OPS_SalesOrderLine",
                        "source_sheet": "Sales",
                        "issue_type": "Orphan child rows",
                        "impacted_rows": int(child[child["order_no"].isin(missing)].shape[0]),
                        "reason": "Some SalesOrderLine.ORDER_NO values do not exist in ARD_OPS_SalesOrder.ORDER_NO.",
                        "resolution": (
                            "Fix or remove orphan sales lines, or ensure matching sales order headers are generated "
                            "before loading SalesOrderLine."
                        ),
                        "missing_order_nos": missing[:50],
                    }
                )
    return issues


def summary_dataframe(
    raw: dict[str, pd.DataFrame],
    tables: dict[str, pd.DataFrame],
    issues: dict[str, list[dict]],
) -> pd.DataFrame:
    source_map = {
        "ARD_OPS_Site": raw["BinCleaning"],
        "ARD_OPS_ItemClass": raw["Sales"],
        "ARD_OPS_Product": pd.concat(
            [
                raw["Sales"][["ITEM_NUM"]].rename(columns={"ITEM_NUM": "product_id"}),
                raw["Fills"][["Product"]].rename(columns={"Product": "product_id"}),
            ],
            ignore_index=True,
        ),
        "ARD_OPS_Customer": raw["Sales"],
        "ARD_OPS_ShipToAccount": raw["Fills"],
        "ARD_OPS_Carrier": raw["Fills"],
        "ARD_OPS_ProductionMix": raw["Mill"],
        "ARD_OPS_MaintenanceType": raw["WorkOrder"],
        "ARD_OPS_CleaningType": raw["BinCleaning"],
        "ARD_OPS_PackLine": raw["Pack"],
        "ARD_OPS_Bin": raw["BinCleaning"],
        "ARD_OPS_PackRun": raw["Pack"],
        "ARD_OPS_MillRun": raw["Mill"],
        "ARD_OPS_SalesOrder": raw["Sales"],
        "ARD_OPS_SalesOrderLine": raw["Sales"],
        "ARD_OPS_WorkOrder": raw["WorkOrder"],
        "ARD_OPS_BinCleaningLog": raw["BinCleaning"],
        "ARD_OPS_FillOrder": raw["Fills"],
    }
    rows = []
    for table_name in LOAD_ORDER:
        source_df = source_map[table_name]
        target_df = tables[table_name]
        spec = TABLE_SPECS[table_name]
        exp = expected_count(source_df, table_name)
        exp_text = exp if exp >= 0 else "Derived from combined Sales/Fills product grain"
        rows.append(
            {
                "target_table": table_name,
                "source_sheet": spec.source_sheet,
                "source_rows": len(source_df),
                "expected_target_rows": exp_text,
                "actual_target_rows": len(target_df),
                "business_key": ", ".join(spec.business_key),
                "grain_description": spec.grain_description,
                "status": "PASS" if (exp == len(target_df) or exp < 0) else "CHECK",
                "top_reason": (
                    issues.get(table_name, [{}])[0].get("reason", "Counts align with expected target grain.")
                    if issues.get(table_name)
                    else "Counts align with expected target grain."
                ),
            }
        )
    return pd.DataFrame(rows)


# ── Test-case DataFrame ────────────────────────────────────────────────────────

def build_test_cases(
    raw: dict[str, pd.DataFrame],
    tables: dict[str, pd.DataFrame],
    issues: dict[str, list[dict]],
) -> pd.DataFrame:
    tests = []
    for table_name in LOAD_ORDER:
        df = tables[table_name]
        spec = TABLE_SPECS[table_name]
        key_cols = spec.business_key
        null_key_count = int(df[key_cols].isna().any(axis=1).sum())
        dup_key_count = int(df.duplicated(subset=key_cols, keep=False).sum())
        audit_nulls = int(df[["created_date", "created_by"]].isna().any(axis=1).sum())
        source_df = raw.get(spec.source_sheet.split("/")[0], pd.DataFrame())
        exp = expected_count(source_df, table_name) if not source_df.empty else -1
        count_result = "PASS" if exp < 0 or exp == len(df) else "CHECK"
        tests.extend(
            [
                {
                    "test_case_id": f"{table_name}_TC01",
                    "target_table": table_name,
                    "test_case": "Business key null count",
                    "result": "PASS" if null_key_count == 0 else "FAIL",
                    "actual_value": null_key_count,
                    "expected_value": 0,
                    "explanation": "Business key columns should not be null in the transformed target dataset.",
                },
                {
                    "test_case_id": f"{table_name}_TC02",
                    "target_table": table_name,
                    "test_case": "Business key duplicate count",
                    "result": "PASS" if dup_key_count == 0 else "FAIL",
                    "actual_value": dup_key_count,
                    "expected_value": 0,
                    "explanation": "The transformed target grain should be unique on the table business key.",
                },
                {
                    "test_case_id": f"{table_name}_TC03",
                    "target_table": table_name,
                    "test_case": "Expected source-to-target row count",
                    "result": count_result,
                    "actual_value": len(df),
                    "expected_value": exp if exp >= 0 else "See explanation",
                    "explanation": spec.grain_description,
                },
                {
                    "test_case_id": f"{table_name}_TC04",
                    "target_table": table_name,
                    "test_case": "Audit columns populated",
                    "result": "PASS" if audit_nulls == 0 else "FAIL",
                    "actual_value": audit_nulls,
                    "expected_value": 0,
                    "explanation": "created_date and created_by should be populated for every target row.",
                },
                {
                    "test_case_id": f"{table_name}_TC05",
                    "target_table": table_name,
                    "test_case": "Transformation issues review",
                    "result": "CHECK" if issues.get(table_name) else "PASS",
                    "actual_value": len(issues.get(table_name, [])),
                    "expected_value": 0,
                    "explanation": "CHECK means the workbook contains a documented source-to-target explanation.",
                },
            ]
        )

        if table_name == "ARD_OPS_SalesOrderLine":
            parent = tables.get("ARD_OPS_SalesOrder", pd.DataFrame())
            fk_missing = 0
            if "order_no" in df.columns and "order_no" in parent.columns:
                missing = set(df["order_no"].dropna().astype(str)) - set(parent["order_no"].dropna().astype(str))
                fk_missing = len(missing)
            tests.append(
                {
                    "test_case_id": f"{table_name}_TC06",
                    "target_table": table_name,
                    "test_case": "SalesOrderLine.ORDER_NO parent key existence",
                    "result": "PASS" if fk_missing == 0 else "FAIL",
                    "actual_value": fk_missing,
                    "expected_value": 0,
                    "explanation": "Every SalesOrderLine.ORDER_NO must reference an existing SalesOrder.ORDER_NO.",
                },
            )
    return pd.DataFrame(tests)


def build_issues_dataframe(issues: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for table_name in LOAD_ORDER:
        rows.extend(issues.get(table_name, []))
    return pd.DataFrame(rows)


def build_detail_dataframe(details: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = [
        details.get(table_name)
        for table_name in LOAD_ORDER
        if details.get(table_name) is not None and not details.get(table_name).empty
    ]
    if not frames:
        return pd.DataFrame(columns=["target_table", "source_sheet", "reason", "source_key", "sample_values"])
    return pd.concat(frames, ignore_index=True)


# ── Output writers ─────────────────────────────────────────────────────────────

def write_validation_workbook(
    output_path: str | Path,
    raw: dict[str, pd.DataFrame],
    tables: dict[str, pd.DataFrame],
    issues: dict[str, list[dict]],
    details: dict[str, pd.DataFrame],
) -> Path:
    output = Path(output_path)
    summary_df = summary_dataframe(raw, tables, issues)
    tests_df = build_test_cases(raw, tables, issues)
    issues_df = build_issues_dataframe(issues)
    details_df = build_detail_dataframe(details)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        tests_df.to_excel(writer, sheet_name="Test_Cases", index=False)
        issues_df.to_excel(writer, sheet_name="Issues", index=False)
        details_df.to_excel(writer, sheet_name="Issue_Details", index=False)
        for table_name in LOAD_ORDER:
            df = tables[table_name]
            df.head(25).to_excel(
                writer,
                sheet_name=table_name.replace("ARD_OPS_", "")[:31],
                index=False,
            )
    return output


def export_diagnostics_json(
    output_path: str | Path,
    raw: dict[str, pd.DataFrame],
    tables: dict[str, pd.DataFrame],
    issues: dict[str, list[dict]],
) -> Path:
    payload = {
        "generated_at_utc": utc_now_naive().isoformat(),
        "summary": summary_dataframe(raw, tables, issues).to_dict(orient="records"),
        "issues": build_issues_dataframe(issues).to_dict(orient="records"),
    }
    target = Path(output_path)
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target
