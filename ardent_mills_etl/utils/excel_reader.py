"""
utils/excel_reader.py
──────────────────────
Reads the Ardent Mills source Excel workbook and returns
a dict of clean DataFrames keyed by sheet name.
"""

from pathlib import Path

import pandas as pd

from config.settings import SOURCE_SHEETS


def load_source_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """
    Read all SOURCE_SHEETS from the workbook.

    Strips column whitespace and injects a 1-based ``_source_row_num``
    column (Excel row number including header row offset) to allow
    issue tracing back to the original file.

    Returns:
        dict[sheet_name, DataFrame]
    """
    workbook = pd.read_excel(path, sheet_name=SOURCE_SHEETS)
    prepared: dict[str, pd.DataFrame] = {}
    for sheet_name, df in workbook.items():
        clean = df.copy()
        clean.columns = clean.columns.str.strip()
        clean.insert(0, "_source_row_num", range(2, len(clean) + 2))
        prepared[sheet_name] = clean
    return prepared
