"""Command-line entry points: `hcm detect`, `hcm features`, `hcm train`, `hcm site`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import typer

from . import config as _config
from . import conversions, features, model

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
    log.info(
        "features: %s rows × %s cols → %s", f"{len(df):,}", df.shape[1], cfg["paths"]["features"]
    )


@app.command()
def train(
    config: Path = typer.Option(None), k: int = typer.Option(200, help="areas in the scouting list")
):
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

        headline["events"] = (
            f"{pq.ParquetFile(cfg['paths']['events']).metadata.num_rows / 1e6:.1f}M"
        )
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


if __name__ == "__main__":
    app()
