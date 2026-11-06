"""Incremental ingest: merge a PDOK mutation file into the staging version table, idempotently.

Design
------
* Key = (id, version). A mutation row with a key already present is a no-op unless it carries a
  later `registered_at` (a correction), in which case it supersedes the stored row.
* Each applied file is recorded in `mutations_applied.parquet` with its content hash, so the same
  file is never applied twice and a re-run of a month is a no-op end to end.
* Writes a fresh partition `part-<yyyymm>.parquet` rather than rewriting history, so staging stays
  append-only and cheap to re-read with DuckDB's glob.

Only the VBO table is handled here; pand mutations follow the same code path with PAND_COLUMNS.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .staging import VBO_COLUMNS

LEDGER = "mutations_applied.parquet"


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _ledger(staging_dir: Path) -> pd.DataFrame:
    p = staging_dir / LEDGER
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=["file", "sha256_16", "applied_at", "rows_in", "rows_new", "rows_superseded"])


def apply_mutation_file(
    mutation_file: str | Path,
    staging_dir: str | Path,
    table: str = "vbo_versions",
    columns: dict = VBO_COLUMNS,
) -> dict:
    """Merge one mutation Parquet file. Returns a small dict describing what happened."""
    mutation_file, staging_dir = Path(mutation_file), Path(staging_dir)
    ledger = _ledger(staging_dir)
    digest = file_hash(mutation_file)
    if digest in set(ledger["sha256_16"]):
        return {"file": mutation_file.name, "status": "already_applied", "rows_new": 0, "rows_superseded": 0}

    con = duckdb.connect()
    cols = ", ".join(columns)
    con.execute(f"CREATE VIEW cur AS SELECT {cols} FROM read_parquet('{staging_dir / table}/*.parquet')")
    con.execute(f"CREATE VIEW mut AS SELECT {cols} FROM read_parquet('{mutation_file}')")
    # rows whose key is unknown, or that are a later registration of a known key
    con.execute("""
        CREATE TABLE delta AS
        SELECT m.* FROM mut m
        LEFT JOIN (SELECT id, version, max(registered_at) AS registered_at FROM cur GROUP BY 1, 2) c
          ON c.id = m.id AND c.version = m.version
        WHERE c.id IS NULL OR m.registered_at > c.registered_at
        QUALIFY row_number() OVER (PARTITION BY m.id, m.version ORDER BY m.registered_at DESC) = 1
    """)
    rows_in = con.execute("SELECT count(*) FROM mut").fetchone()[0]
    rows_new = con.execute("""SELECT count(*) FROM delta d
                              WHERE NOT EXISTS (SELECT 1 FROM cur c WHERE c.id = d.id AND c.version = d.version)""").fetchone()[
        0
    ]
    rows_sup = con.execute("SELECT count(*) FROM delta").fetchone()[0] - rows_new

    if rows_new + rows_sup > 0:
        # supersede: mark the older registration ended at the new registration time, in a new partition
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        out = staging_dir / table / f"part-mut-{stamp}-{digest}.parquet"
        con.execute(f"""
            COPY (
              SELECT d.* FROM delta d
              UNION ALL
              SELECT c.id, c.version, c.valid_from, c.valid_to, c.registered_at, d.registered_at AS registration_ended_at,
                     {", ".join("c." + c for c in columns if c not in ("id", "version", "valid_from", "valid_to", "registered_at", "registration_ended_at"))}
              FROM cur c JOIN delta d ON d.id = c.id AND d.version = c.version AND c.registration_ended_at IS NULL
            ) TO '{out}' (FORMAT PARQUET)
        """)
        # the superseded originals still exist in older partitions; readers de-duplicate on (id, version, registered_at)
        # keeping the row with the latest registration_ended_at, which `staging.connect()` views handle via QUALIFY.

    entry = pd.DataFrame(
        [
            {
                "file": mutation_file.name,
                "sha256_16": digest,
                "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rows_in": int(rows_in),
                "rows_new": int(rows_new),
                "rows_superseded": int(rows_sup),
            }
        ]
    )
    pd.concat([ledger, entry], ignore_index=True).to_parquet(staging_dir / LEDGER, index=False)
    con.close()
    return {
        "file": mutation_file.name,
        "status": "applied",
        "rows_in": int(rows_in),
        "rows_new": int(rows_new),
        "rows_superseded": int(rows_sup),
    }


def apply_all(mutations_dir: str | Path, staging_dir: str | Path) -> list[dict]:
    """Apply every *.parquet in `mutations_dir` in name order (PDOK names are date-ordered)."""
    results = [apply_mutation_file(p, staging_dir) for p in sorted(Path(mutations_dir).glob("*.parquet"))]
    print(json.dumps(results, indent=1))
    return results
