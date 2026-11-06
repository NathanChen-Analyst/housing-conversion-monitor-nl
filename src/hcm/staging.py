"""Staging layer: typed version tables and point-in-time snapshots over them.

The BAG is a type-2 slowly changing dimension with two timelines (validity and registration).
See docs/data-model.md. Everything here is DuckDB over Parquet and works on the full national
extract as well as on the synthetic sample.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

VBO_COLUMNS = {
    "id": "VARCHAR",
    "version": "INTEGER",
    "valid_from": "DATE",
    "valid_to": "DATE",
    "registered_at": "TIMESTAMP",
    "registration_ended_at": "TIMESTAMP",
    "status": "VARCHAR",
    "gebruiksdoel": "VARCHAR",
    "oppervlakte_m2": "DOUBLE",
    "pand_id": "VARCHAR",
    "x": "DOUBLE",
    "y": "DOUBLE",
}
PAND_COLUMNS = {
    "id": "VARCHAR",
    "version": "INTEGER",
    "valid_from": "DATE",
    "valid_to": "DATE",
    "registered_at": "TIMESTAMP",
    "registration_ended_at": "TIMESTAMP",
    "status": "VARCHAR",
    "bouwjaar": "INTEGER",
}


def connect(staging_dir: str | Path) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with `vbo_versions` and `pand_versions` views over the staging Parquet."""
    staging_dir = Path(staging_dir)
    con = duckdb.connect()
    for name in ("vbo_versions", "pand_versions"):
        if not (staging_dir / name).exists():
            continue
        # A mutation can re-emit a stored version with `registration_ended_at` filled in (see hcm.mutations).
        # Reading all partitions, keep the most informative copy of each (id, version, registered_at).
        con.execute(f"""
            CREATE VIEW {name} AS
            SELECT * FROM read_parquet('{staging_dir / name}/*.parquet', union_by_name = true)
            QUALIFY row_number() OVER (PARTITION BY id, version, registered_at
                                       ORDER BY registration_ended_at DESC NULLS LAST) = 1
        """)
    return con


def _snapshot_sql(table: str, as_of: str, by: str) -> str:
    """Rows of `table` alive at `as_of`. by='validity' = what was true; by='registration' = what was known."""
    cond = f"valid_from <= DATE '{as_of}' AND (valid_to IS NULL OR valid_to > DATE '{as_of}')"
    if by == "registration":
        cond += (
            f" AND registered_at <= TIMESTAMP '{as_of}'"
            f" AND (registration_ended_at IS NULL OR registration_ended_at > TIMESTAMP '{as_of}')"
        )
    elif by == "validity":
        cond += " AND registration_ended_at IS NULL"
    else:
        raise ValueError("by must be 'validity' or 'registration'")
    return f"""
        SELECT * FROM {table}
        WHERE {cond}
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY version DESC, registered_at DESC) = 1
    """


def snapshot(
    con: duckdb.DuckDBPyConnection, as_of: str, table: str = "vbo_versions", by: str = "validity"
) -> pd.DataFrame:
    """One row per object alive on `as_of` (ISO date)."""
    return con.execute(_snapshot_sql(table, as_of, by)).df()


def yearly_snapshots(
    con: duckdb.DuckDBPyConnection,
    years: range | list[int],
    table: str = "vbo_versions",
    by: str = "validity",
) -> pd.DataFrame:
    """Stack of 1-January snapshots with a `year` column: the stock table the detector works on."""
    parts = " UNION ALL ".join(
        f"SELECT {y} AS year, * FROM ({_snapshot_sql(table, f'{y}-01-01', by)})" for y in years
    )
    return con.execute(parts).df()


def write_snapshots(
    con: duckdb.DuckDBPyConnection, years: range | list[int], out_dir: str | Path, by: str = "validity"
) -> Path:
    """Materialise marts/stock_snapshots/year=YYYY/part-0.parquet (Hive-partitioned)."""
    out_dir = Path(out_dir)
    for y in years:
        p = out_dir / f"year={y}"
        p.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY ({_snapshot_sql('vbo_versions', f'{y}-01-01', by)}) TO '{p / 'part-0.parquet'}' (FORMAT PARQUET)"
        )
    return out_dir


def version_table_stats(con: duckdb.DuckDBPyConnection, table: str = "vbo_versions") -> dict:
    """Row counts and SCD2 sanity figures, used by the quality layer and the run log."""
    r = con.execute(f"""
        SELECT count(*) AS versions, count(DISTINCT id) AS objects,
               sum(CASE WHEN valid_to IS NULL THEN 1 ELSE 0 END) AS open_versions,
               sum(CASE WHEN registration_ended_at IS NOT NULL THEN 1 ELSE 0 END) AS superseded_registrations,
               median(date_diff('day', valid_from, registered_at::DATE)) AS median_registration_lag_days,
               sum(CASE WHEN valid_to < valid_from THEN 1 ELSE 0 END) AS negative_validity_spans
        FROM {table}
    """).fetchone()
    keys = [
        "versions",
        "objects",
        "open_versions",
        "superseded_registrations",
        "median_registration_lag_days",
        "negative_validity_spans",
    ]
    return dict(
        zip(
            keys,
            (
                int(v) if isinstance(v, (int, float)) and k != "median_registration_lag_days" else v
                for k, v in zip(keys, r)
            ),
        )
    )
