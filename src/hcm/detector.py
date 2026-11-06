"""Detector entry point with a private/illustrative switch.

If a module named `hcm_private.detector` is importable (installed from the private repository), its
`detect(snapshots, versions) -> events` is used. Otherwise the illustrative pattern detector ships with
this repository. Both return the same grain: one row per converted dwelling.
"""

from __future__ import annotations

import importlib
import logging

import duckdb
import pandas as pd

log = logging.getLogger("hcm.detector")


def which() -> str:
    try:
        importlib.import_module("hcm_private.detector")
        return "production (private)"
    except ModuleNotFoundError:
        return "illustrative"


def detect(con: duckdb.DuckDBPyConnection, first_year: int, last_year: int) -> pd.DataFrame:
    """Return events with columns vbo_id, pand_id, event_date, reg_date, oppervlakte_m2, x, y."""
    try:
        mod = importlib.import_module("hcm_private.detector")
        log.info("using production detector")
        return mod.detect(con, first_year, last_year)
    except ModuleNotFoundError:
        log.info("using illustrative detector (use_change pattern)")
    return con.execute(f"""
        WITH ordered AS (
            SELECT *, lag(list_contains(string_split(lower(coalesce(gebruiksdoel, '')), ','), 'woonfunctie'))
                        OVER (PARTITION BY id ORDER BY version) AS prev_res,
                   list_contains(string_split(lower(coalesce(gebruiksdoel, '')), ','), 'woonfunctie') AS is_res
            FROM vbo_versions WHERE registration_ended_at IS NULL
        ),
        flips AS (
            SELECT id AS vbo_id, pand_id, valid_from AS event_date, registered_at AS reg_date, oppervlakte_m2, x, y,
                   row_number() OVER (PARTITION BY id ORDER BY valid_from) AS rn
            FROM ordered WHERE is_res AND prev_res = false
        )
        SELECT vbo_id, pand_id, event_date, reg_date, oppervlakte_m2, x, y
        FROM flips WHERE rn = 1 AND year(event_date) BETWEEN {first_year} AND {last_year}
        ORDER BY event_date, vbo_id
    """).df()
