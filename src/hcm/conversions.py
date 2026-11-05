"""Detect non-residential → residential conversions from BAG lifecycle events.

Input: an *events* table with one row per BAG `voorkomen` (version) of a
verblijfsobject (VBO). Required columns:

    vbo_id            str   BAG identificatie of the verblijfsobject
    pand_id           str   BAG identificatie of the (first) pand it sits in
    begin_geldigheid  date  start of validity of this version
    tijdstip_reg      date  when the municipality registered this version
    status            str   VBO status, e.g. "Verblijfsobject in gebruik"
    gebruiksdoel      str   comma-separated uses, e.g. "kantoorfunctie,woonfunctie"
    oppervlakte       float floor area in m²
    pand_bouwjaar     int   construction year of the pand
    pand_status       str   pand status at the same moment (optional, for pattern 3)
    wijk_code         str   reference-vintage wijk the VBO falls in (from point-in-polygon)

Output: one row per detected conversion with the pattern that fired, the event
date, and the registration date. Downstream code must use `tijdstip_reg`
(registration), never `begin_geldigheid`, when deciding what a forecast made at
time T is allowed to know.

Three patterns, each documented where implemented:

  use_change           same VBO, previous version had no woonfunctie, new version has one
  new_unit_in_old_pand first residential VBO appearing in a pand built >= N years earlier
  after_verbouwing     residential VBO count in a pand increases after a "Verbouwing pand" status

Implemented in DuckDB SQL over a pandas frame so it scales to the full national
extract (tens of millions of rows) without leaving a laptop.
"""

from __future__ import annotations

import duckdb
import pandas as pd

RESIDENTIAL = "woonfunctie"
IN_USE = "Verblijfsobject in gebruik"

REQUIRED = [
    "vbo_id",
    "pand_id",
    "begin_geldigheid",
    "tijdstip_reg",
    "status",
    "gebruiksdoel",
    "oppervlakte",
    "pand_bouwjaar",
    "wijk_code",
]


def _check_schema(events: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events table missing columns: {missing}")
    if "pand_status" not in events.columns:
        events["pand_status"] = None


def detect(
    events: pd.DataFrame,
    min_pand_age_years: int = 2,
    patterns: tuple[str, ...] = ("use_change", "new_unit_in_old_pand", "after_verbouwing"),
) -> pd.DataFrame:
    """Return detected conversions.

    Columns: vbo_id, pand_id, wijk_code, pattern, event_date (begin_geldigheid),
    reg_date (tijdstip_reg), oppervlakte, from_use (uses before, if known).
    """
    _check_schema(events)
    con = duckdb.connect()
    con.register("ev", events)
    con.execute(f"""
        CREATE TEMP TABLE v AS
        SELECT *,
               list_contains(string_split(lower(coalesce(gebruiksdoel, '')), ','), '{RESIDENTIAL}') AS is_res,
               status = '{IN_USE}' AS in_use,
               row_number() OVER (PARTITION BY vbo_id ORDER BY begin_geldigheid, tijdstip_reg) AS seq
        FROM ev
    """)

    parts = []

    if "use_change" in patterns:
        # Pattern 1: the VBO itself changes use. We take the first version where
        # woonfunctie appears after at least one earlier version without it.
        parts.append("""
            SELECT cur.vbo_id, cur.pand_id, cur.wijk_code, 'use_change' AS pattern,
                   cur.begin_geldigheid AS event_date, cur.tijdstip_reg AS reg_date,
                   cur.oppervlakte, prev.gebruiksdoel AS from_use
            FROM v cur
            JOIN v prev ON prev.vbo_id = cur.vbo_id AND prev.seq = cur.seq - 1
            WHERE cur.is_res AND NOT prev.is_res
              AND cur.seq = (
                  SELECT min(c2.seq) FROM v c2 JOIN v p2 ON p2.vbo_id = c2.vbo_id AND p2.seq = c2.seq - 1
                  WHERE c2.vbo_id = cur.vbo_id AND c2.is_res AND NOT p2.is_res)
        """)

    if "new_unit_in_old_pand" in patterns:
        # Pattern 2: a residential VBO is created (its first version is already
        # residential) inside a pand that is old enough that this cannot be new
        # construction, and the pand had no residential VBO before that date.
        parts.append(f"""
            WITH first_ver AS (
                SELECT * FROM v WHERE seq = 1
            ),
            first_res_in_pand AS (
                SELECT pand_id, min(begin_geldigheid) AS first_res_date
                FROM v WHERE is_res GROUP BY pand_id
            )
            SELECT f.vbo_id, f.pand_id, f.wijk_code, 'new_unit_in_old_pand' AS pattern,
                   f.begin_geldigheid AS event_date, f.tijdstip_reg AS reg_date,
                   f.oppervlakte, NULL AS from_use
            FROM first_ver f
            JOIN first_res_in_pand r ON r.pand_id = f.pand_id
            WHERE f.is_res
              AND f.pand_bouwjaar IS NOT NULL
              AND year(f.begin_geldigheid) - f.pand_bouwjaar >= {int(min_pand_age_years)}
              AND f.begin_geldigheid = r.first_res_date
              -- the pand must have had at least one non-residential VBO before this date
              AND EXISTS (SELECT 1 FROM v n WHERE n.pand_id = f.pand_id
                          AND NOT n.is_res AND n.begin_geldigheid < f.begin_geldigheid)
        """)

    if "after_verbouwing" in patterns:
        # Pattern 3: a pand goes through "Verbouwing pand" and afterwards gains
        # residential VBOs that did not exist before the renovation started.
        parts.append("""
            WITH verb AS (
                SELECT pand_id, min(begin_geldigheid) AS verb_date
                FROM v WHERE pand_status = 'Verbouwing pand' GROUP BY pand_id
            )
            SELECT f.vbo_id, f.pand_id, f.wijk_code, 'after_verbouwing' AS pattern,
                   f.begin_geldigheid AS event_date, f.tijdstip_reg AS reg_date,
                   f.oppervlakte, NULL AS from_use
            FROM v f
            JOIN verb ON verb.pand_id = f.pand_id
            WHERE f.seq = 1 AND f.is_res AND f.begin_geldigheid > verb.verb_date
        """)

    if not parts:
        return pd.DataFrame(
            columns=[
                "vbo_id",
                "pand_id",
                "wijk_code",
                "pattern",
                "event_date",
                "reg_date",
                "oppervlakte",
                "from_use",
            ]
        )

    sql = " UNION ALL ".join(f"SELECT * FROM ({p})" for p in parts)
    out = con.execute(f"""
        WITH allp AS ({sql}),
        ranked AS (
            -- one conversion per VBO: keep the earliest event, tie-break by pattern priority
            SELECT *, row_number() OVER (
                PARTITION BY vbo_id
                ORDER BY event_date,
                         CASE pattern WHEN 'use_change' THEN 1 WHEN 'new_unit_in_old_pand' THEN 2 ELSE 3 END
            ) AS rn
            FROM allp)
        SELECT vbo_id, pand_id, wijk_code, pattern, event_date, reg_date, oppervlakte, from_use
        FROM ranked WHERE rn = 1
        ORDER BY event_date, vbo_id
    """).df()
    con.close()
    return out


def aggregate(conversions: pd.DataFrame, by: str = "wijk_code", freq: str = "year") -> pd.DataFrame:
    """Count conversions per area per period, using the *event* date.

    For model targets this is fine (the target is what actually happened); for
    *features* use `registered_before()` so nothing registered after the forecast
    date leaks in.
    """
    df = conversions.copy()
    df["event_date"] = pd.to_datetime(df["event_date"])
    if freq == "year":
        df["period"] = df["event_date"].dt.year
    elif freq == "quarter":
        df["period"] = df["event_date"].dt.to_period("Q").astype(str)
    else:
        raise ValueError("freq must be 'year' or 'quarter'")
    return (
        df.groupby([by, "period"])
        .agg(n_conversions=("vbo_id", "size"), floor_area=("oppervlakte", "sum"))
        .reset_index()
    )


def registered_before(conversions: pd.DataFrame, as_of: str | pd.Timestamp) -> pd.DataFrame:
    """Subset to conversions the register knew about at `as_of` (by tijdstip_reg)."""
    as_of = pd.Timestamp(as_of)
    df = conversions.copy()
    df["reg_date"] = pd.to_datetime(df["reg_date"])
    return df[df["reg_date"] <= as_of]
