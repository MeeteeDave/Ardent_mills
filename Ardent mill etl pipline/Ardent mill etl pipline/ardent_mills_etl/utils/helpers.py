"""
utils/helpers.py
─────────────────
Shared helper functions: text normalization, hashing, audit columns,
site name parsing, and unknown-dimension-row insertion.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config.settings import CREATED_BY, UNKNOWN_TEXT


LEGAL_SUFFIX_PATTERN = re.compile(
    r"\b(INC|INCORPORATED|LLC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY)\b\.?",
    re.IGNORECASE,
)


# ── Date/time ──────────────────────────────────────────────────────────────────

def utc_now_naive() -> datetime:
    """Return current UTC time without tzinfo (Oracle does not want tz-aware)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Text normalization ─────────────────────────────────────────────────────────

def normalize_text(value) -> str | None:
    """Strip whitespace; normalize numeric IDs; return None for blank/NaN values."""
    if pd.isna(value):
        return None
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_upper(value) -> str | None:
    """normalize_text + upper-case."""
    text = normalize_text(value)
    return text.upper() if text else None


def customer_identity_key(value) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    text = LEGAL_SUFFIX_PATTERN.sub("", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text or None


# ── Surrogate / stable ID generation ──────────────────────────────────────────

def stable_bigint(*parts) -> int:
    """SHA-1–based deterministic integer ID from one or more key parts."""
    text = "||".join("" if part is None else str(part) for part in parts)
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:15], 16)


def assign_sequence_ids(df: pd.DataFrame, id_col: str, start: int) -> pd.DataFrame:
    """Prepend a sequential integer PK column starting at *start*."""
    out = df.reset_index(drop=True).copy()
    out.insert(0, id_col, pd.array(range(start, start + len(out)), dtype="Int64"))
    return out


def assign_stable_ids(
    df: pd.DataFrame,
    id_col: str,
    key_cols: list[str] | str,
    offset: int = 9000000000,
    width: int = 10,
) -> pd.DataFrame:
    """Add a deterministic integer ID based on stable business key values."""
    cols = [key_cols] if isinstance(key_cols, str) else list(key_cols)
    out = df.copy()
    basis = out[cols].fillna("").astype(str).agg("||".join, axis=1)
    range_size = 10 ** (width - 1)
    out[id_col] = pd.Series(
        [(stable_bigint(value) % range_size) + offset for value in basis],
        dtype="Int64",
    )
    return out


def assign_stable_id(df: pd.DataFrame, id_col: str, key_cols: list[str]) -> pd.DataFrame:
    """Add a SHA-1–derived stable integer ID based on *key_cols*."""
    out = df.copy()
    basis = out[key_cols].apply(
        lambda row: "||".join("" if pd.isna(v) else str(v) for v in row.tolist()),
        axis=1,
    )
    occurrence = basis.groupby(basis, dropna=False).cumcount().add(1)
    out[id_col] = [stable_bigint(b, occ) for b, occ in zip(basis, occurrence)]
    out[id_col] = out[id_col].astype("Int64")
    return out


# ── Audit columns ──────────────────────────────────────────────────────────────

def _snapshot_candidates() -> list[Path]:
    package_root = Path(__file__).resolve().parents[1]
    project_root = Path(__file__).resolve().parents[4]
    return [
        project_root / "production_pipelines" / "history" / "current_snapshot.json",
        package_root / "Ardent_Mills_ETL_Snapshot.json",
        Path.cwd() / "Ardent_Mills_ETL_Snapshot.json",
    ]


def _key_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value)


def _row_key_frame(df: pd.DataFrame, key_cols: list[str]) -> pd.Series:
    return df[key_cols].map(_key_value).agg("||".join, axis=1)


def load_existing_id_map(
    table_name: str,
    key_cols: list[str] | str,
    id_col: str,
    include_occurrence: bool = False,
) -> dict[str, int]:
    cols = [key_cols] if isinstance(key_cols, str) else list(key_cols)
    for path in _snapshot_candidates():
        if not path.exists():
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = snapshot.get(table_name, [])
        if not rows:
            continue
        previous = pd.DataFrame(rows)
        if (
            table_name == "ARD_OPS_Customer"
            and "customer_identity_key" in cols
            and "customer_identity_key" not in previous.columns
            and "customer_nm" in previous.columns
        ):
            previous["customer_identity_key"] = previous["customer_nm"].apply(customer_identity_key)
        if not set(cols + [id_col]).issubset(previous.columns):
            continue
        basis = _row_key_frame(previous, cols)
        if include_occurrence:
            basis = basis + "||#" + basis.groupby(basis, dropna=False).cumcount().add(1).astype(str)
        mapping: dict[str, int] = {}
        for key, value in zip(basis, previous[id_col]):
            if pd.isna(value):
                continue
            try:
                id_value = int(value)
            except (TypeError, ValueError):
                continue
            key_text = str(key)
            if key_text in mapping:
                mapping[key_text] = min(mapping[key_text], id_value)
            else:
                mapping[key_text] = id_value
        if mapping:
            return mapping
    return {}


def assign_preserved_ids(
    df: pd.DataFrame,
    table_name: str,
    id_col: str,
    key_cols: list[str] | str,
    start: int,
    include_occurrence: bool = False,
) -> pd.DataFrame:
    """
    Preserve existing IDs by business key and assign new IDs at the end.

    This avoids row-position IDs shifting when source rows are inserted.
    """
    cols = [key_cols] if isinstance(key_cols, str) else list(key_cols)
    out = df.reset_index(drop=True).copy()
    if id_col in out.columns:
        out = out.drop(columns=[id_col])

    existing_map = load_existing_id_map(table_name, cols, id_col, include_occurrence)
    basis = _row_key_frame(out, cols)
    if include_occurrence:
        basis = basis + "||#" + basis.groupby(basis, dropna=False).cumcount().add(1).astype(str)

    assigned = basis.map(existing_map)
    used_ids = {int(value) for value in assigned.dropna().tolist()}
    next_id = max([start - 1, *existing_map.values(), *used_ids]) + 1
    values: list[int] = []
    for value in assigned.tolist():
        if pd.notna(value):
            values.append(int(value))
            continue
        while next_id in used_ids:
            next_id += 1
        values.append(next_id)
        used_ids.add(next_id)
        next_id += 1

    out.insert(0, id_col, pd.array(values, dtype="Int64"))
    return out


def add_audit(df: pd.DataFrame) -> pd.DataFrame:
    """Append created_date, created_by, updated_date, updated_by audit columns."""
    out = df.copy()
    now = utc_now_naive()
    out["created_date"] = now
    out["created_by"] = CREATED_BY
    out["updated_date"] = None
    out["updated_by"] = None
    return out


# ── Site name parsing ──────────────────────────────────────────────────────────

def parse_site_short_name(series: pd.Series) -> pd.DataFrame:
    """
    Parse 'SiteName-1234' format into {'site_name': str, 'site_id': Int64}.
    Handles mixed formats gracefully.
    """
    clean = series.astype(str).str.strip()
    return pd.DataFrame(
        {
            "site_name": clean.str.split("-").str[0].str.strip().str.title(),
            "site_id": pd.to_numeric(
                clean.str.extract(r"-(\d+)$")[0], errors="coerce"
            ).astype("Int64"),
        }
    )


# ── Unknown dimension row ──────────────────────────────────────────────────────

def add_unknown_dimension_row(
    df: pd.DataFrame, key_col: str, natural_col: str, extra: dict | None = None
) -> pd.DataFrame:
    """Prepend an UNKNOWN sentinel row (key=0) to a dimension DataFrame."""
    extra = extra or {}
    unknown = {col: None for col in df.columns}
    unknown[key_col] = 0
    unknown[natural_col] = UNKNOWN_TEXT
    unknown.update(extra)
    return pd.concat([pd.DataFrame([unknown]), df], ignore_index=True)
