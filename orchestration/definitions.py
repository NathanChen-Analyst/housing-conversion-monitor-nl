"""Dagster assets for the Housing Conversion Monitor.

    dagster dev -f orchestration/definitions.py        # UI with the asset graph
    dagster asset materialize -f orchestration/definitions.py --select '*'

Each asset wraps one hcm function so the same code runs from the CLI, from tests, and from here.
Asset checks block publishing when a quality check with severity "error" fails.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from dagster import (
    AssetCheckResult,
    Definitions,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    asset_check,
    define_asset_job,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hcm import config as hcm_config  # noqa: E402
from hcm import detector, geo, mutations, quality, staging  # noqa: E402
from hcm.export_public import export_public  # noqa: E402

CFG = hcm_config.load()
DATA = ROOT / "data"
STAGING, MARTS, RAW = DATA / "staging", DATA / "marts", DATA / "raw"
YEARS = range(CFG["time"]["start_year"], CFG["time"]["end_year"] + 1)
RUNLOG = ROOT / "runs" / "runs.jsonl"


def _log_run(step: str, started: float, **kw) -> None:
    RUNLOG.parent.mkdir(exist_ok=True)
    with open(RUNLOG, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "step": step,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "seconds": round(time.time() - started, 2),
                    **kw,
                }
            )
            + "\n"
        )


# ------------------------------------------------------------------ bronze → silver


@asset(
    group_name="silver",
    description="Apply every PDOK mutation file in data/raw/mutations to the staging version table (idempotent).",
)
def vbo_versions(context) -> MaterializeResult:
    t = time.time()
    results = mutations.apply_all(RAW / "mutations", STAGING) if (RAW / "mutations").exists() else []
    stats = staging.version_table_stats(staging.connect(STAGING))
    _log_run("vbo_versions", t, **stats, mutation_files=len(results))
    return MaterializeResult(
        metadata={
            "versions": stats["versions"],
            "objects": stats["objects"],
            "median_registration_lag_days": MetadataValue.float(
                float(stats["median_registration_lag_days"] or 0)
            ),
            "mutation_files_seen": len(results),
            "mutation_files_applied": sum(1 for r in results if r["status"] == "applied"),
        }
    )


@asset_check(asset=vbo_versions, description="pandera schema, SCD2 invariants, referential integrity")
def vbo_versions_quality() -> AssetCheckResult:
    qr = quality.QualityRun(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    quality.check_staging(qr, STAGING)
    return AssetCheckResult(
        passed=qr.ok,
        metadata={c.name: ("pass" if c.passed else f"{c.severity}: {c.observed}") for c in qr.checks},
    )


# ------------------------------------------------------------------ silver → gold


@asset(
    deps=[vbo_versions],
    group_name="gold",
    description="1-January stock of every VBO per year, Hive-partitioned by year.",
)
def stock_snapshots() -> MaterializeResult:
    t = time.time()
    out = staging.write_snapshots(staging.connect(STAGING), YEARS, MARTS / "stock_snapshots")
    n = sum(len(pd.read_parquet(p)) for p in out.glob("year=*/part-0.parquet"))
    _log_run("stock_snapshots", t, rows=n, years=len(YEARS))
    return MaterializeResult(metadata={"rows": n, "years": len(YEARS), "path": str(out)})


@asset(
    deps=[stock_snapshots],
    group_name="gold",
    description="One row per converted dwelling. Production detector if installed, else illustrative.",
)
def conversion_events() -> MaterializeResult:
    t = time.time()
    ev = detector.detect(staging.connect(STAGING), YEARS.start, YEARS.stop - 1)
    MARTS.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(MARTS / "conversion_events.parquet", index=False)
    _log_run("conversion_events", t, rows=len(ev), detector=detector.which())
    return MaterializeResult(
        metadata={
            "rows": len(ev),
            "detector": detector.which(),
            "by_year": MetadataValue.md(
                pd.to_datetime(ev["event_date"])
                .dt.year.value_counts()
                .sort_index()
                .to_frame("n")
                .to_markdown()
            ),
        }
    )


@asset(
    deps=[conversion_events],
    group_name="gold",
    description="Events assigned by coordinate to the reference buurt/wijk/gemeente vintage.",
)
def events_located() -> MaterializeResult:
    t = time.time()
    ev = pd.read_parquet(MARTS / "conversion_events.parquet")
    buurt_path = CFG["paths"]["wijk_geo"] if CFG["paths"]["wijk_geo"].exists() else RAW / "buurt_sample.gpkg"
    buurten = geo.load_buurten(buurt_path)
    pts = gpd.GeoDataFrame(ev, geometry=gpd.points_from_xy(ev["x"], ev["y"]), crs=geo.RD_NEW)
    located = geo.assign_areas(pts, buurten)
    unlocated = int(located["WK_CODE"].isna().sum())
    located = located[located["WK_CODE"].notna()].copy()
    located["Identificatie"] = located["vbo_id"]  # column names export_public expects
    located["Begin Geldigheid"] = located["event_date"]
    pd.DataFrame(located.drop(columns="geometry")).to_parquet(MARTS / "events_located.parquet", index=False)
    geo.export_wijk_geojson(buurten, MARTS / "wijken.geojson")
    _log_run("events_located", t, rows=len(located), unlocated=unlocated, boundaries=str(buurt_path.name))
    return MaterializeResult(
        metadata={"rows": len(located), "unlocated_dropped": unlocated, "boundaries": buurt_path.name}
    )


@asset(
    deps=[events_located],
    group_name="publish",
    description="wijk × year counts with small-cell suppression; CSV/JSON for the site.",
)
def wijk_year(context) -> MaterializeResult:
    t = time.time()
    ev = pd.read_parquet(MARTS / "events_located.parquet")
    summary = export_public(ev, MARTS / "public", first_year=YEARS.start, last_year=YEARS.stop - 1)
    context.log.info(summary)
    _log_run("wijk_year", t)
    return MaterializeResult(metadata={"summary": MetadataValue.md("```\n" + summary + "\n```")})


@asset_check(asset=wijk_year, description="grid completeness, suppression rule, hidden share")
def wijk_year_quality() -> AssetCheckResult:
    wy = pd.read_csv(MARTS / "public" / "wijk_year_conversions.csv")
    gy = pd.read_csv(MARTS / "public" / "gemeente_year_conversions.csv")
    qr = quality.QualityRun(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    quality.check_wijk_year(
        qr, wy, gy, CFG["conversion"].get("suppress_below", 3) if "suppress_below" in CFG["conversion"] else 3
    )
    return AssetCheckResult(
        passed=qr.ok,
        metadata={c.name: ("pass" if c.passed else f"{c.severity}: {c.observed}") for c in qr.checks},
    )


@asset(
    deps=[wijk_year],
    group_name="publish",
    description="Quality report page (docs/quality.html) from all layers.",
)
def quality_report() -> MaterializeResult:
    t = time.time()
    raw_n = len(pd.read_parquet(MARTS / "conversion_events.parquet"))
    ev = pd.read_parquet(MARTS / "events_located.parquet").rename(columns={"WK_CODE": "wijk_code"})
    wy = pd.read_csv(MARTS / "public" / "wijk_year_conversions.csv")
    gy = pd.read_csv(MARTS / "public" / "gemeente_year_conversions.csv")
    cbs = None
    cbs_path = RAW / "cbs_transformaties.csv"  # year,n — drop in when available
    if cbs_path.exists():
        c = pd.read_csv(cbs_path)
        cbs = pd.Series(c["n"].values, index=c["year"].values)
    qr = quality.run(STAGING, ev, wy, gy, cbs, YEARS.start, YEARS.stop - 1)
    dropped = raw_n - len(ev)
    qr.add(
        "marts",
        "events dropped as unlocated",
        dropped / max(raw_n, 1) <= 0.01,
        severity="warn",
        observed=f"{dropped} of {raw_n:,} ({dropped / max(raw_n, 1):.2%})",
        expected="≤ 1%",
    )
    out = quality.report(qr, ROOT / "docs" / "quality.html", MARTS / "quality.json")
    _log_run("quality_report", t, ok=qr.ok, checks=len(qr.checks))
    return MaterializeResult(metadata={"ok": qr.ok, "checks": len(qr.checks), "report": str(out)})


@asset(
    deps=[quality_report],
    group_name="publish",
    description="Placeholder for the one-year-ahead forecast (hcm.model). Not yet materialised.",
)
def forecast() -> MaterializeResult:
    return MaterializeResult(metadata={"status": "pending — see src/hcm/model.py and sql/features.sql"})


monthly = ScheduleDefinition(
    job=define_asset_job("refresh", selection="*"),
    cron_schedule="0 6 10 * *",
    description="PDOK publishes the monthly mutation file around the 8th.",
)

defs = Definitions(
    assets=[
        vbo_versions,
        stock_snapshots,
        conversion_events,
        events_located,
        wijk_year,
        quality_report,
        forecast,
    ],
    asset_checks=[vbo_versions_quality, wijk_year_quality],
    schedules=[monthly],
)
