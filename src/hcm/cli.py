"""Command-line entry points: `hcm detect`, `hcm features`, `hcm train`, `hcm site`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import typer

from . import config as _config
from . import conversions, features, model, mutations, quality, staging

app = typer.Typer(help="Housing Conversion Monitor NL", no_args_is_help=True)
log = logging.getLogger("hcm")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@app.command()
def detect(config: Path = typer.Option(None, help="Path to config.yaml")):
    """Detect conversions from the processed events table."""
    cfg = _config.load(config)
    ev = pd.read_parquet(cfg["paths"]["events"])
    log.info("loaded %s events", f"{len(ev):,}")
    out = conversions.detect(
        ev, cfg["conversion"]["min_pand_age_years"], tuple(cfg["conversion"]["patterns"])
    )
    out.to_parquet(cfg["paths"]["conversions"], index=False)
    log.info("detected %s conversions → %s", f"{len(out):,}", cfg["paths"]["conversions"])
    log.info("by pattern:\n%s", out["pattern"].value_counts().to_string())


@app.command("features")
def features_cmd(config: Path = typer.Option(None)):
    """Build the wijk × year feature table."""
    cfg = _config.load(config)
    df = features.build_from_files(cfg["paths"])
    df.to_parquet(cfg["paths"]["features"], index=False)
    log.info("features: %s rows × %s cols → %s", f"{len(df):,}", df.shape[1], cfg["paths"]["features"])


@app.command()
def train(config: Path = typer.Option(None), k: int = typer.Option(200, help="areas in the scouting list")):
    """Fit baseline, NB GLM and LightGBM; print validation and test metrics."""
    cfg = _config.load(config)
    df = pd.read_parquet(cfg["paths"]["features"])
    t = cfg["time"]
    res = model.run_all(
        df, t["train_until"], t["validate_year"], t["test_year"], cfg["model"].get("monotone"), k=k
    )
    cfg["paths"]["model_dir"].mkdir(parents=True, exist_ok=True)
    res.to_csv(cfg["paths"]["model_dir"] / "metrics.csv", index=False)
    typer.echo(res.round(3).to_string(index=False))


@app.command()
def site(config: Path = typer.Option(None)):
    """Export forecasts and drivers as JSON for the docs/ map."""
    cfg = _config.load(config)
    out_dir = cfg["paths"]["site_data"]
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(cfg["paths"]["features"])
    t = cfg["time"]
    cols = model.feature_columns(df)
    tr, _, _ = model.split(df, t["train_until"], t["validate_year"], t["test_year"])
    m = model.fit_lgbm(tr, cols, cfg["model"].get("monotone"))
    df["forecast"] = m.predict(df)
    headline = {}
    metrics_path = cfg["paths"]["model_dir"] / "metrics.csv"
    if metrics_path.exists():
        met = pd.read_csv(metrics_path).set_index(["model", "split"])
        try:
            base, lg = met.loc[("seasonal_naive", "test")], met.loc[("lgbm_tweedie", "test")]
            headline["mae_vs_baseline"] = f"{(lg['mae'] / base['mae'] - 1):+.0%}".replace("-", "−")
            cap = next(c for c in met.columns if c.startswith("capture_at_"))
            headline["capture_at_200"] = f"{lg[cap]:.2f}"
        except KeyError:
            log.warning("metrics.csv found but missing test rows; headline left empty")
    if cfg["paths"]["events"].exists():
        import pyarrow.parquet as pq

        headline["events"] = f"{pq.ParquetFile(cfg['paths']['events']).metadata.num_rows / 1e6:.1f}M"
    payload = {
        "meta": {
            "unit": cfg["space"]["unit"],
            "years": sorted(df.year.unique().tolist()),
            "test_year": t["test_year"],
            "synthetic": False,
            "headline": headline,
        },
        "areas": {
            w: {
                "forecast": g.set_index("year")["forecast"].round(1).to_dict(),
                "actual": g.set_index("year")[model.TARGET].to_dict(),
            }
            for w, g in df.groupby("wijk_code")
        },
    }
    (out_dir / "forecasts.json").write_text(json.dumps(payload), encoding="utf-8")
    log.info("wrote %s", out_dir / "forecasts.json")


@app.command()
def sample():
    """Generate the synthetic BAG-like sample (data/staging, data/raw/mutations, buurt_sample.gpkg)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_sample_data", _config.ROOT / "scripts" / "make_sample_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(_config.ROOT / "data")


@app.command()
def ingest(mutations_dir: Path = typer.Argument(None, help="Folder with PDOK mutation Parquet files")):
    """Merge monthly mutation files into data/staging (idempotent; re-running a month is a no-op)."""
    mdir = mutations_dir or _config.ROOT / "data" / "raw" / "mutations"
    mutations.apply_all(mdir, _config.ROOT / "data" / "staging")


@app.command()
def snapshot(
    year: int = typer.Argument(..., help="1 January of this year"),
    by: str = typer.Option("validity", help="validity | registration"),
):
    """Print the size of the VBO stock on 1 January of a year, as it was or as it was known."""
    con = staging.connect(_config.ROOT / "data" / "staging")
    df = staging.snapshot(con, f"{year}-01-01", by=by)
    typer.echo(f"{len(df):,} VBOs alive on {year}-01-01 ({by} time)")
    typer.echo(df["gebruiksdoel"].value_counts().head(8).to_string())


@app.command("quality")
def quality_cmd(out: Path = typer.Option(None, help="HTML report path (default docs/quality.html)")):
    """Run every data-quality check on the staging layer and write the HTML report."""
    qr = quality.run(_config.ROOT / "data" / "staging")
    html = quality.report(qr, out or _config.ROOT / "docs" / "quality.html")
    for c in qr.checks:
        typer.echo(f"{'PASS' if c.passed else c.severity.upper():5s} {c.layer:8s} {c.name:45s} {c.observed}")
    typer.echo(f"report → {html}")
    raise typer.Exit(code=0 if qr.ok else 1)


@app.command()
def pipeline():
    """Materialise every Dagster asset once (same as `dagster asset materialize --select '*'`)."""
    import subprocess

    subprocess.run(
        [
            "dagster",
            "asset",
            "materialize",
            "-f",
            str(_config.ROOT / "orchestration" / "definitions.py"),
            "--select",
            "*",
        ],
        check=True,
    )


if __name__ == "__main__":
    app()
