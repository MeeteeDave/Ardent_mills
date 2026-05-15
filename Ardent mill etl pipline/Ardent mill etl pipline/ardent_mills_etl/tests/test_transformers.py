"""
tests/test_transformers.py
───────────────────────────
Unit tests for key transformer functions.
Run with: python -m pytest tests/
"""

import pandas as pd
import pytest

from utils.helpers import (
    assign_stable_ids,
    normalize_text,
    normalize_upper,
    parse_site_short_name,
    stable_bigint,
)


# ── normalize_text ────────────────────────────────────────────────────────────

def test_normalize_text_strips_whitespace():
    assert normalize_text("  hello  ") == "hello"

def test_normalize_text_nan_returns_none():
    assert normalize_text(float("nan")) is None

def test_normalize_text_empty_string_returns_none():
    assert normalize_text("   ") is None


def test_normalize_text_float_integer_is_normalized():
    assert normalize_text(28882452485.0) == "28882452485"
    assert normalize_text("28882452485.0") == "28882452485"


def test_build_sales_order_normalizes_numeric_order_no():
    from transformers.dimensions import build_customer
    from transformers.facts import build_sales_order

    raw = {
        "Sales": pd.DataFrame(
            {
                "_source_row_num": [2, 3],
                "SITE_SHORT_NAME": ["Albany-1001", "Albany-1001"],
                "CUSTOMER_NM": ["Acme Corp", "Acme Corp"],
                "ORDER_NO": [28882452485.0, "28882452485"],
                "ITEM_NUM": ["P1", "P2"],
                "SHIP_DATE": [None, None],
                "ORDER_STATUS_INDICATOR": [None, None],
                "INVOICE_CWTS": [1.0, 2.0],
            }
        )
    }
    customer_df, _, _ = build_customer(raw)
    order_df, line_df, _, _ = build_sales_order(raw, customer_df, {"P1", "P2"})

    assert order_df["order_no"].astype(str).tolist() == ["28882452485"]
    assert line_df["order_no"].astype(str).tolist() == ["28882452485", "28882452485"]


def test_normalize_upper():
    assert normalize_upper("  hello  ") == "HELLO"


# ── parse_site_short_name ─────────────────────────────────────────────────────

def test_parse_site_short_name_basic():
    s = pd.Series(["Albany-1001", "Ogden-1025"])
    result = parse_site_short_name(s)
    assert result["site_id"].tolist() == [1001, 1025]
    assert result["site_name"].tolist() == ["Albany", "Ogden"]

def test_parse_site_short_name_missing_id():
    s = pd.Series(["Albany"])
    result = parse_site_short_name(s)
    assert pd.isna(result["site_id"].iloc[0])


# ── stable_bigint ─────────────────────────────────────────────────────────────

def test_stable_bigint_deterministic():
    a = stable_bigint("product123", 1)
    b = stable_bigint("product123", 1)
    assert a == b

def test_stable_bigint_different_inputs():
    assert stable_bigint("A", 1) != stable_bigint("B", 1)


def test_assign_stable_ids_deterministic():
    df = pd.DataFrame({"key": ["A", "B", "A"]})
    result = assign_stable_ids(df, "stable_id", ["key"], offset=9000000000)
    assert result["stable_id"].iloc[0] == result["stable_id"].iloc[2]
    assert result["stable_id"].nunique() == 2


def test_build_sales_order_stable_order_ids():
    from transformers.dimensions import build_customer
    from transformers.facts import build_sales_order

    raw = {
        "Sales": pd.DataFrame(
            {
                "_source_row_num": [2, 3, 4],
                "SITE_SHORT_NAME": ["Albany-1001", "Albany-1001", "Albany-1001"],
                "CUSTOMER_NM": ["Acme Corp", "Acme Corp", "Beta LLC"],
                "ORDER_NO": ["O1", "O1", "O2"],
                "ITEM_NUM": ["P1", "P2", "P3"],
                "SHIP_DATE": [None, None, None],
                "ORDER_STATUS_INDICATOR": [None, None, None],
                "INVOICE_CWTS": [1.0, 2.0, 3.0],
            }
        )
    }

    customer_df, _, _ = build_customer(raw)
    order_df1, line_df1, _, _ = build_sales_order(raw, customer_df, {"P1", "P2", "P3"})
    order_df2, line_df2, _, _ = build_sales_order(raw, customer_df, {"P1", "P2", "P3"})

    assert order_df1["order_id"].tolist() == order_df2["order_id"].tolist()
    assert line_df1["order_line_id"].tolist() == line_df2["order_line_id"].tolist()
    assert order_df1["order_id"].nunique() == len(order_df1)
    assert line_df1["order_line_id"].nunique() == len(line_df1)


def test_build_match_key_groups_sales_order_uses_order_no_only():
    from loaders.oracle_loader import build_match_key_groups

    groups = build_match_key_groups(
        "ARD_OPS_SalesOrder",
        ["order_id", "order_no", "site_id"],
        ["order_no"],
    )

    assert groups == [["order_no"]]


def test_sales_order_line_fk_validation_reports_missing_parent_order_no():
    from utils.validation import find_foreign_key_issues

    tables = {
        "ARD_OPS_SalesOrder": pd.DataFrame(
            {"order_id": [45000], "order_no": ["O1"]}
        ),
        "ARD_OPS_SalesOrderLine": pd.DataFrame(
            {
                "order_line_id": [30000, 30001],
                "order_no": ["O1", "O2"],
                "product_id": ["P1", "P2"],
                "invoice_cwts": [1.0, 2.0],
            }
        ),
    }

    issues = find_foreign_key_issues(tables)
    assert len(issues) == 1
    assert issues[0]["target_table"] == "ARD_OPS_SalesOrderLine"
    assert "O2" in issues[0]["missing_order_nos"]


def test_build_sales_order_line_ids_unique_for_repeated_line_values():
    from transformers.dimensions import build_customer
    from transformers.facts import build_sales_order

    raw = {
        "Sales": pd.DataFrame(
            {
                "_source_row_num": [2, 3, 4, 5],
                "SITE_SHORT_NAME": ["Albany-1001"] * 4,
                "CUSTOMER_NM": ["Acme Corp"] * 4,
                "ORDER_NO": ["O1", "O1", "O1", "O1"],
                "ITEM_NUM": ["P1", "P1", "P1", "P1"],
                "SHIP_DATE": [None, None, None, None],
                "ORDER_STATUS_INDICATOR": [None, None, None, None],
                "INVOICE_CWTS": [1.0, 1.0, 1.0, 1.0],
            }
        )
    }

    customer_df, _, _ = build_customer(raw)
    _, line_df, _, _ = build_sales_order(raw, customer_df, {"P1"})
    assert len(line_df) == 4
    assert line_df["order_line_id"].nunique() == 4


def test_build_work_order_stable_workorder_pk():
    from transformers.facts import build_work_order

    raw = {
        "WorkOrder": pd.DataFrame(
            {
                "_source_row_num": [2, 3],
                "SITE_SHORT_NAME": ["Albany-1001", "Albany-1001"],
                "MAINTENANCE_TYP": ["PM", "PM"],
                "WO_NO": ["WO1", "WO2"],
                "CATEGORY_CD": [None, None],
                "STATUS_CD": [None, None],
                "PREVENTIVE_CORRECTIVE_IND": [None, None],
                "LATE_INDICATOR": [None, None],
                "REQUIRED_DATE": [None, None],
                "WO_COUNT": [None, None],
                "WO_LATE_COUNT": [None, None],
                "WO_ONTIME_COUNT": [None, None],
                "WO_UPCOMING_COUNT": [None, None],
            }
        )
    }

    maintenance_df = pd.DataFrame({"maintenance_type": ["PM"], "maintenance_type_id": [15000]})
    out1, _, _ = build_work_order(raw, maintenance_df)
    out2, _, _ = build_work_order(raw, maintenance_df)
    assert out1["workorder_pk"].tolist() == out2["workorder_pk"].tolist()
    assert out1["workorder_pk"].nunique() == len(out1)


# ── build_customer (duplicate fix) ────────────────────────────────────────────

def _make_raw_customer():
    """Simulate a Sales sheet with duplicate customer names."""
    return {
        "Sales": pd.DataFrame(
            {
                "_source_row_num": [2, 3, 4, 5],
                "CUSTOMER_NM": ["Acme Corp", "Acme Corp", "Beta LLC", "Beta LLC"],
                # Minimal extra columns needed by other functions (unused here)
                "SITE_SHORT_NAME": ["A-1", "A-1", "B-2", "B-2"],
                "ORDER_NO": ["O1", "O2", "O3", "O4"],
                "ITEM_NUM": ["P1", "P2", "P3", "P4"],
                "ITEM_DESC": ["d1", "d2", "d3", "d4"],
                "ITEM_CLASS_DESC": ["c1", "c1", "c2", "c2"],
                "SHIP_DATE": [None, None, None, None],
                "ORDER_STATUS_INDICATOR": [None, None, None, None],
                "INVOICE_CWTS": [1.0, 2.0, 3.0, 4.0],
            }
        )
    }


def test_build_customer_no_duplicate_ids():
    from transformers.dimensions import build_customer
    raw = _make_raw_customer()
    df, issues, _ = build_customer(raw)
    # Two unique names → two rows
    assert len(df) == 2
    # customer_id must be unique
    assert df["customer_id"].nunique() == 2
    # customer_nm must be unique
    assert df["customer_nm"].nunique() == 2
    # One duplicate issue logged
    assert any(i["issue_type"] == "Duplicate source grain collapsed" for i in issues)


def test_build_customer_ids_are_stable_and_offset_from_3000():
    from transformers.dimensions import build_customer
    raw = _make_raw_customer()
    df1, _, _ = build_customer(raw)
    df2, _, _ = build_customer(raw)
    ids = sorted(df1["customer_id"].tolist())
    assert len(ids) == 2
    assert all(id_val >= 3000 for id_val in ids)
    assert df1["customer_id"].tolist() == df2["customer_id"].tolist()


def test_build_customer_preserves_existing_ids_when_new_name_sorts_first(monkeypatch):
    from transformers import dimensions
    from utils import helpers

    monkeypatch.setattr(
        helpers,
        "load_existing_id_map",
        lambda *args, **kwargs: {"ORLANDO FOODS INC": 3069, "ZETA FOODS": 3070},
    )
    raw = {
        "Sales": pd.DataFrame(
            {
                "_source_row_num": [2, 3, 4],
                "CUSTOMER_NM": ["JERSEY FOODS", "ORLANDO FOODS INC", "ZETA FOODS"],
            }
        )
    }

    df, _, _ = dimensions.build_customer(raw)
    id_map = df.set_index("customer_nm")["customer_id"].to_dict()

    assert id_map["ORLANDO FOODS INC"] == 3069
    assert id_map["ZETA FOODS"] == 3070
    assert id_map["JERSEY FOODS"] == 3071


# ── build_site deduplication ──────────────────────────────────────────────────

def _make_minimal_raw():
    sheets = {}
    for sheet in ["Pack", "Mill", "Sales", "WorkOrder"]:
        sheets[sheet] = pd.DataFrame(
            {"_source_row_num": [2, 3], "SITE_SHORT_NAME": ["Albany-1001", "Albany-1001"]}
        )
    sheets["BinCleaning"] = pd.DataFrame(
        {
            "_source_row_num": [2],
            "SHORTPLANTNAME": ["Albany"],
            "SITE_ID_OPS": [1001],
            "OPS_TYPE": ["Pack"],
            "REGION": ["Northeast"],
            "PACKPLANT": [1],
            "COMPANY": ["AM"],
            "COUNTRY_CD": ["US"],
        }
    )
    return sheets


def test_build_site_no_duplicate_site_ids():
    from transformers.dimensions import build_site
    raw = _make_minimal_raw()
    df, _, _ = build_site(raw)
    assert df["site_id"].nunique() == df["site_id"].count()


# ── build_item_class ──────────────────────────────────────────────────────────

def test_build_item_class_unique_ids():
    from transformers.dimensions import build_item_class
    raw = {
        "Sales": pd.DataFrame(
            {"_source_row_num": [2, 3, 4], "ITEM_CLASS_DESC": ["Flour", "Flour", "Grain"]}
        )
    }
    df, _, _ = build_item_class(raw)
    assert len(df) == 2
    assert df["item_class_id"].nunique() == 2
