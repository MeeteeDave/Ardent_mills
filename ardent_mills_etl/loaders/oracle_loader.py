"""
loaders/oracle_loader.py
─────────────────────────
Handles all Oracle connectivity and incremental upsert logic.

Incremental load strategy
──────────────────────────
Each table uses Oracle MERGE:
  • WHEN MATCHED  → UPDATE all non-key columns
  • WHEN NOT MATCHED → INSERT

Duplicate prevention (belt-and-suspenders)
──────────────────────────────────────────
1. Transformer-level  : every builder calls drop_duplicates(subset=key)
2. Loader-level       : run_single_table drops duplicates again before MERGE
3. Oracle-level       : MERGE ON clause guarantees exactly one matched target row
"""

import logging
from typing import Any

import pandas as pd
import oracledb

from config.settings import ORACLE_CONFIG, CREATED_BY
from config.table_specs import TABLE_SPECS, LOAD_ORDER

LOGGER = logging.getLogger("ardent_etl.loader")


# ── Connection helpers ─────────────────────────────────────────────────────────

def make_oracle_dsn(cfg: dict) -> str:
    if cfg.get("dsn"):
        return cfg["dsn"]
    host = cfg["host"]
    port = cfg.get("port", 1521)
    service_name = cfg.get("service_name")
    sid = cfg.get("sid")
    if service_name:
        return f"{host}:{port}/{service_name}"
    if sid:
        return f"{host}:{port}/{sid}"
    raise ValueError("Oracle config must include either dsn, service_name, or sid.")


def open_oracle_connection(cfg: dict) -> oracledb.Connection:
    if cfg.get("thick_mode"):
        try:
            oracledb.init_oracle_client()
        except Exception:
            pass
    return oracledb.connect(
        user=cfg["username"],
        password=cfg["password"],
        dsn=make_oracle_dsn(cfg),
    )


def test_oracle_connection(cfg: dict) -> tuple[bool, str]:
    try:
        with open_oracle_connection(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dual")
                cur.fetchone()
        return True, "Oracle connection OK"
    except Exception as exc:
        return False, str(exc)


# ── Schema inspection ──────────────────────────────────────────────────────────

def get_oracle_table_columns(conn: oracledb.Connection, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT LOWER(column_name) FROM user_tab_columns WHERE table_name = UPPER(:t)",
            {"t": table_name},
        )
        return {row[0] for row in cur.fetchall()}


def get_oracle_identity_columns(conn: oracledb.Connection, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT LOWER(column_name) FROM user_tab_cols WHERE table_name = UPPER(:t) AND identity_column = 'YES'",
            {"t": table_name},
        )
        return {row[0] for row in cur.fetchall()}


def resolve_oracle_table_name(conn: oracledb.Connection, table_name: str) -> str:
    candidates = [table_name, table_name.upper()]
    if table_name.upper() == "ARD_OPS_WORKORDER":
        candidates += ["ARD_OPS_WORK_ORDER", "ARD_OPS_WORKODER"]
    for candidate in candidates:
        if get_oracle_table_columns(conn, candidate):
            return candidate
    return table_name


def oracle_column_exists(conn: oracledb.Connection, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM user_tab_columns
               WHERE table_name = UPPER(:t) AND column_name = UPPER(:c)""",
            {"t": table_name, "c": column_name},
        )
        return cur.fetchone()[0] > 0


def describe_oracle_constraint(conn: oracledb.Connection, constraint_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.table_name, c.constraint_type,
                   LISTAGG(cc.column_name, ', ') WITHIN GROUP (ORDER BY cc.position)
            FROM user_constraints c
            JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
            WHERE c.constraint_name = UPPER(:cn)
            GROUP BY c.table_name, c.constraint_type
            """,
            {"cn": constraint_name},
        )
        row = cur.fetchone()
    if not row:
        return f"constraint {constraint_name} not found in USER_CONSTRAINTS"
    ctype = {"P": "PRIMARY KEY", "U": "UNIQUE", "R": "FOREIGN KEY"}.get(row[1], row[1])
    return f"{row[0]} {ctype} ({row[2]})"


# ── Data-type helpers ──────────────────────────────────────────────────────────

def _safe_db_value(value: Any) -> Any:
    """Convert pandas NA / numpy scalars to Python-native types for oracledb."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def is_loader_pk_col(col: str) -> bool:
    """Identify surrogate PK columns that should be excluded from MERGE SET clauses."""
    lowered = col.lower()
    return lowered.endswith("_pk") or lowered in {
        "order_id", "item_class_id", "customer_id", "carrier_id", "production_mix_id",
        "maintenance_type_id", "line_id", "order_line_id", "fill_order_id",
        "cleaning_log_id", "pack_run_id", "mill_run_id",
    }


# ── Match-key logic ────────────────────────────────────────────────────────────

def build_match_key_groups(table_name: str, cols: list[str], key_cols: list[str]) -> list[list[str]]:
    upper = table_name.upper()
    if upper == "ARD_OPS_MAINTENANCETYPE" and {"maintenance_type_id", "maintenance_type"}.issubset(cols):
        return [["maintenance_type_id"], ["maintenance_type"]]
    if upper == "ARD_OPS_SALESORDER" and {"order_no"}.issubset(cols):
        return [["order_no"]]
    if upper == "ARD_OPS_SALESORDERLINE" and {"order_line_id", "order_no", "product_id", "invoice_cwts"}.issubset(cols):
        return [["order_line_id"], ["order_no", "product_id", "invoice_cwts"]]
    if upper == "ARD_OPS_WORKORDER" and {"workorder_pk", "wo_no"}.issubset(cols):
        return [["workorder_pk"], ["wo_no"]]
    return [key_cols]


def build_on_clause(match_key_groups: list[list[str]]) -> str:
    group_clauses = [
        " AND ".join(f"t.{k} = s.{k}" for k in group)
        for group in match_key_groups
    ]
    return " OR ".join(f"({c})" for c in group_clauses)


# ── Product FK resolution ──────────────────────────────────────────────────────

def fetch_product_code_to_id_map(conn: oracledb.Connection) -> dict[str, int]:
    if not oracle_column_exists(conn, "ARD_OPS_PRODUCT", "product_code"):
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT product_code, product_id FROM ARD_OPS_PRODUCT WHERE product_code IS NOT NULL"
        )
        return {str(code).strip(): pid for code, pid in cur.fetchall()}


def resolve_product_fk_values(
    out: pd.DataFrame, table_name: str, target_cols: set[str], conn: oracledb.Connection
) -> pd.DataFrame:
    if table_name.upper() == "ARD_OPS_PRODUCT":
        return out
    if "product_id" not in out.columns or "product_id" not in target_cols:
        return out
    product_map = fetch_product_code_to_id_map(conn)
    if not product_map:
        return out
    resolved = out.copy()
    original = resolved["product_id"]
    mapped = original.apply(lambda v: product_map.get(str(v).strip()) if pd.notna(v) else None)
    missing = int(original.notna().sum() - mapped.notna().sum())
    if missing:
        LOGGER.warning("%s: %d product_id values not found in ARD_OPS_PRODUCT.PRODUCT_CODE → set NULL", table_name, missing)
    resolved["product_id"] = mapped.astype("Int64")
    return resolved


# ── DataFrame → Oracle column alignment ───────────────────────────────────────

def align_dataframe_to_oracle_table(
    df: pd.DataFrame, table_name: str, key_cols: list[str], conn: oracledb.Connection
) -> tuple[pd.DataFrame, list[str], set[str]]:
    table_name = resolve_oracle_table_name(conn, table_name)
    target_cols = get_oracle_table_columns(conn, table_name)
    if not target_cols:
        raise ValueError(f"Oracle table not found or has no visible columns: {table_name}")

    out = df.copy()
    keys = list(key_cols)

    if table_name.upper() == "ARD_OPS_PRODUCT" and "product_code" in target_cols:
        if "product_code" not in out.columns and "product_id" in out.columns:
            out = out.rename(columns={"product_id": "product_code"})
        keys = ["product_code" if k == "product_id" else k for k in keys]
    else:
        out = resolve_product_fk_values(out, table_name, target_cols, conn)

    cols_to_drop = [c for c in out.columns if c.lower() not in target_cols]
    if cols_to_drop:
        LOGGER.debug("%s: dropping columns not in Oracle schema: %s", table_name, cols_to_drop)
        out = out.drop(columns=cols_to_drop)

    missing_keys = [k for k in keys if k not in out.columns]
    if missing_keys:
        raise ValueError(f"Missing MERGE key columns for {table_name}: {missing_keys}")

    return out, keys, target_cols


def _batch_sequence(values: list[Any], batch_size: int = 900) -> list[list[Any]]:
    return [values[i : i + batch_size] for i in range(0, len(values), batch_size)]


def get_oracle_table_count(conn: oracledb.Connection, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        return int(cur.fetchone()[0])


def verify_sales_order_line_parent_keys(conn: oracledb.Connection, df: pd.DataFrame) -> None:
    if "order_no" not in df.columns or df["order_no"].dropna().empty:
        return

    order_nos = sorted(set(df["order_no"].dropna().astype(str)))
    if not order_nos:
        return

    parent_order_nos: set[str] = set()
    for batch in _batch_sequence(order_nos, batch_size=900):
        placeholders = ", ".join(f":p{i}" for i in range(len(batch)))
        sql = f"SELECT DISTINCT order_no FROM ARD_OPS_SALESORDER WHERE order_no IN ({placeholders})"
        binds = {f"p{i}": value for i, value in enumerate(batch)}
        with conn.cursor() as cur:
            cur.execute(sql, binds)
            parent_order_nos.update(row[0] for row in cur.fetchall())

    missing = [value for value in order_nos if value not in parent_order_nos]
    if missing:
        raise ValueError(
            "Missing parent ORDER_NO values in ARD_OPS_SALESORDER for ARD_OPS_SALESORDERLINE: "
            + ", ".join(str(m) for m in missing[:50])
            + ("..." if len(missing) > 50 else "")
        )


# ── Core MERGE upsert ──────────────────────────────────────────────────────────

def upsert_dataframe(df: pd.DataFrame, table_name: str, key_cols: list[str], cfg: dict) -> None:
    conn = open_oracle_connection(cfg)
    try:
        table_name = resolve_oracle_table_name(conn, table_name)
        df, key_cols, target_cols = align_dataframe_to_oracle_table(df, table_name, key_cols, conn)

        if table_name.upper() == "ARD_OPS_SALESORDER":
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE ARD_OPS_SALESORDERLINE")
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE ARD_OPS_SALESORDER")
            conn.commit()
            LOGGER.info("%s: truncated child and parent tables before load", table_name)

        if table_name.upper() == "ARD_OPS_SALESORDERLINE":
            verify_sales_order_line_parent_keys(conn, df)

        # Loader-level duplicate guard
        before = len(df)
        df = df.drop_duplicates(subset=key_cols).copy()
        if len(df) < before:
            LOGGER.warning("%s: removed %d duplicate rows before MERGE", table_name, before - len(df))

        cols = list(df.columns)
        match_key_groups = build_match_key_groups(table_name, cols, key_cols)
        on_clause = build_on_clause(match_key_groups)
        match_key_cols = {c for group in match_key_groups for c in group}
        audit_cols = {"created_date", "created_by", "updated_date", "updated_by"}
        update_cols = [c for c in cols if c not in match_key_cols and not is_loader_pk_col(c) and c not in audit_cols]

        identity_cols = get_oracle_identity_columns(conn, table_name)
        override_clause = " OVERRIDING SYSTEM VALUE" if identity_cols and any(c in identity_cols for c in cols) else ""

        audit_update = [col for col in ["updated_date", "updated_by"] if col in target_cols]
        audit_clause = (
            ", ".join(
                ["t.updated_date = SYSDATE"]
                + [f"t.updated_by = '{CREATED_BY}'"]
            )
            if audit_update
            else ""
        )

        if update_cols:
            change_condition = " OR ".join(f"t.{c} != s.{c}" for c in update_cols)
            set_clause = ", ".join(f"t.{c} = s.{c}" for c in update_cols)
            if audit_clause:
                set_clause = f"{set_clause}, {audit_clause}"
            when_matched = f"WHEN MATCHED THEN UPDATE SET {set_clause} WHERE {change_condition}"
        elif audit_clause:
            when_matched = f"WHEN MATCHED THEN UPDATE SET {audit_clause}"
        else:
            when_matched = ""

        merge_sql = f"""
            MERGE INTO {table_name} t
            USING (
                SELECT {', '.join(f':{i+1} AS {c}' for i, c in enumerate(cols))}
                FROM dual
            ) s
            ON ({on_clause})
            {when_matched}
            WHEN NOT MATCHED THEN
                INSERT ({', '.join(cols)})
                VALUES ({', '.join(f's.{c}' for c in cols)}){override_clause}
        """

        bind_rows = [
            tuple(_safe_db_value(v) for v in row)
            for row in df[cols].itertuples(index=False, name=None)
        ]

        with conn.cursor() as cur:
            cur.executemany(merge_sql, bind_rows)
        conn.commit()
        target_count = get_oracle_table_count(conn, table_name)
        LOGGER.info(
            "✓ %s processed: %d rows (target table count: %d)",
            table_name,
            len(df),
            target_count,
        )

    except Exception as exc:
        LOGGER.error("✗ FAILED TABLE: %s — %s", table_name, exc)
        msg = str(exc)
        if ("unique constraint" in msg or "integrity constraint" in msg) and "(" in msg and ")" in msg:
            constraint_name = msg.split("(", 1)[1].split(")", 1)[0].split(".")[-1]
            try:
                LOGGER.error("  Constraint details: %s", describe_oracle_constraint(conn, constraint_name))
            except Exception:
                pass
        raise

    finally:
        conn.close()


# ── Public API ─────────────────────────────────────────────────────────────────

def run_single_table(tables: dict[str, pd.DataFrame], table_name: str, cfg: dict) -> None:
    if table_name not in tables:
        LOGGER.error("%s not found in tables dict", table_name)
        return
    df = tables[table_name]
    if df is None or df.empty:
        LOGGER.warning("%s is empty, skipping load", table_name)
        return

    spec = TABLE_SPECS[table_name]
    physical_name = spec.physical_table_name or table_name.upper()
    key_cols = spec.loader_key

    # Loader-level dedup before hand-off
    before = len(df)
    df = df.drop_duplicates(subset=key_cols, keep="first").copy()
    if len(df) < before:
        LOGGER.warning("%s: removed %d duplicate rows based on %s", table_name, before - len(df), key_cols)

    try:
        upsert_dataframe(df, physical_name, key_cols, cfg)
    except Exception as exc:
        LOGGER.error("Error loading %s: %s", physical_name, exc)
        raise


def run_all_tables(tables: dict[str, pd.DataFrame], cfg: dict) -> None:
    for table_name in LOAD_ORDER:
        LOGGER.info("Loading %s …", table_name)
        run_single_table(tables, table_name, cfg)
