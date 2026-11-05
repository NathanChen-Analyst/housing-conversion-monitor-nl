"""Public, aggregated layer for the map: wijk × year conversion counts with small-cell suppression.

Input: one row per converted VBO (version) with at least
    Identificatie, <year column>, WK_CODE, BU_CODE, GM_CODE, GM_NAAM
Output in save_dir:
    wijk_year_conversions.json      read by docs/app.js
    wijk_year_conversions.csv       same numbers, for GitHub / citation
    buurt_year_conversions.csv      buurt level (published only if you decide to)
    gemeente_year_conversions.csv   municipality roll-up, no suppression needed
    export_summary.txt              what was dropped / suppressed
Nothing below area × year leaves this module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SUPPRESS_BELOW = 3
MEASURE = "converted dwellings"


def _dedupe(df: pd.DataFrame, year_col: str, first_year: int, last_year: int) -> pd.DataFrame:
    d = pd.DataFrame(df.drop(columns="geometry", errors="ignore"))
    d["year"] = pd.to_datetime(d[year_col], errors="coerce").dt.year
    d = d[d["year"].between(first_year, last_year)].dropna(subset=["WK_CODE", "BU_CODE"])
    # one dwelling counted once, at its earliest version
    return d.sort_values(["Identificatie", year_col]).drop_duplicates("Identificatie", keep="first")


def _aggregate(d: pd.DataFrame, level: str, years: list[int], suppress_below: int):
    agg = d.groupby([level, "year"]).size().rename("n").reset_index()
    grid = pd.MultiIndex.from_product([sorted(d[level].unique()), years], names=[level, "year"]).to_frame(
        index=False
    )
    agg = grid.merge(agg, how="left").fillna({"n": 0}).astype({"n": int})
    agg["suppressed"] = (agg["n"] > 0) & (agg["n"] < suppress_below)
    pub = agg.copy()
    pub.loc[pub["suppressed"], "n"] = pd.NA
    return agg, pub


def export_public(
    df: pd.DataFrame,
    save_dir: str | Path,
    *,
    year_col: str = "Begin Geldigheid",
    first_year: int = 2012,
    last_year: int = 2024,
    suppress_below: int = SUPPRESS_BELOW,
    author: str = "Nathan Chen",
) -> str:
    """Write the four public files and return the summary text."""
    save = Path(save_dir)
    save.mkdir(parents=True, exist_ok=True)
    d = _dedupe(df, year_col, first_year, last_year)
    years = list(range(first_year, last_year + 1))

    wijk_raw, wijk_pub = _aggregate(d, "WK_CODE", years, suppress_below)
    buurt_raw, buurt_pub = _aggregate(d, "BU_CODE", years, suppress_below)
    gem = d.groupby(["GM_CODE", "GM_NAAM", "year"]).size().rename("n").reset_index()
    wk_name = d.groupby("WK_CODE")["GM_NAAM"].agg(lambda s: s.mode().iat[0]).to_dict()

    wijk_pub.rename(columns={"WK_CODE": "wijk_code"}).to_csv(save / "wijk_year_conversions.csv", index=False)
    buurt_pub.rename(columns={"BU_CODE": "buurt_code"}).to_csv(
        save / "buurt_year_conversions.csv", index=False
    )
    gem.to_csv(save / "gemeente_year_conversions.csv", index=False)

    areas = {}
    for w, g in wijk_pub.groupby("WK_CODE"):
        g = g.set_index("year")
        areas[w] = {
            "name": wk_name.get(w, w),
            "n": {int(y): (None if pd.isna(v) else int(v)) for y, v in g["n"].items()},
            "suppressed": [int(y) for y, s in g["suppressed"].items() if s],
        }
    payload = {
        "meta": {
            "unit": "wijk",
            "years": years,
            "measure": MEASURE,
            "suppress_below": suppress_below,
            "source": "Kadaster BAG (CC0), own detection",
            "license": "CC BY 4.0",
            "author": author,
            "generated": pd.Timestamp.today().strftime("%Y-%m-%d"),
        },
        "areas": areas,
    }
    (save / "wijk_year_conversions.json").write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )

    def supp(name, raw):
        hidden = raw.loc[raw["suppressed"], "n"].sum()
        return (
            f"{name:7s} cells {len(raw):>7,}  non-zero {int((raw.n > 0).sum()):>6,}  "
            f"suppressed {int(raw['suppressed'].sum()):>6,}  hidden {int(hidden):>6,} ({hidden / len(d):.1%})"
        )

    summary = "\n".join(
        [
            f"input rows              {len(df):,}",
            f"dwellings after dedup   {len(d):,}   (years {first_year}-{last_year})",
            "",
            supp("wijk", wijk_raw),
            supp("buurt", buurt_raw),
            "",
            "by year:",
            d.groupby("year").size().to_string(),
            "",
            "top 15 gemeenten:",
            gem.groupby("GM_NAAM")["n"].sum().sort_values(ascending=False).head(15).to_string(),
        ]
    )
    (save / "export_summary.txt").write_text(summary, encoding="utf-8")
    return summary
