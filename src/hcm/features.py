"""Build the wijk × year feature table with DuckDB (SQL lives in sql/features.sql)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .config import ROOT

SQL_PATH = ROOT / "sql" / "features.sql"


def build(
    conv: pd.DataFrame, stock: pd.DataFrame, cbs: pd.DataFrame, nb: pd.DataFrame
) -> pd.DataFrame:
    con = duckdb.connect()
    for name, df in {"conv": conv, "stock": stock, "cbs": cbs, "nb": nb}.items():
        con.register(name, df)
    out = con.execute(SQL_PATH.read_text(encoding="utf-8")).df()
    con.close()
    return out


def build_from_files(paths: dict[str, Path]) -> pd.DataFrame:
    read = pd.read_parquet
    conv = read(paths["conversions"])
    proc = paths["conversions"].parent
    return build(
        conv,
        read(proc / "stock.parquet"),
        read(proc / "cbs.parquet"),
        read(proc / "neighbours.parquet"),
    )


def assert_no_leakage(features: pd.DataFrame, conv: pd.DataFrame) -> None:
    """Recompute conversions_lag1 using only reg_date <= forecast date and compare.

    If anyone later edits the SQL and accidentally joins on event_date, this fails.
    """
    conv = conv.copy()
    conv["reg_date"] = pd.to_datetime(conv["reg_date"])
    conv["event_date"] = pd.to_datetime(conv["event_date"])
    for (w, y), row in features.set_index(["wijk_code", "year"]).iterrows():
        as_of = pd.Timestamp(year=y - 1, month=12, day=31)
        known = conv[
            (conv.wijk_code == w) & (conv.reg_date <= as_of) & (conv.event_date.dt.year == y - 1)
        ]
        assert len(known) == row["conversions_lag1"], (
            f"leakage or mismatch at {w}/{y}: feature={row['conversions_lag1']}, recomputed={len(known)}"
        )
