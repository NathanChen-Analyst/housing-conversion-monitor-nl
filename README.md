# Housing Conversion Monitor NL

**Where will offices become homes next year?**
Detection and one-year-ahead forecast of non-residential → residential conversions for every Dutch neighbourhood (wijk), built from Kadaster BAG lifecycle data and CBS statistics.

**Live map:** https://YOUR_GITHUB_USERNAME.github.io/housing-conversion-monitor-nl/
**Status:** pipeline and site scaffold complete; numbers on the live map are synthetic until the first real run is published.

[![ci](https://github.com/YOUR_GITHUB_USERNAME/housing-conversion-monitor-nl/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_GITHUB_USERNAME/housing-conversion-monitor-nl/actions)

---

## Why this exists

Roughly ten thousand Dutch dwellings a year are not built; they are *converted* from offices, shops, schools and care buildings. For a developer or investor the question is not how many, but **where next** and **which buildings**. This project turns the national building register into that answer:

- a ranked **scouting list** of neighbourhoods most likely to see conversions next year,
- the **drivers** behind each forecast (non-residential stock, build decade, momentum in neighbouring areas, prices),
- and a **municipal benchmark** of how long permit → occupancy takes, from the register's own timestamps.

## What it does

| Step | Command | Output |
|---|---|---|
| Detect conversions from VBO lifecycle events | `hcm detect` | `data/processed/conversions.parquet` |
| Build wijk × year features in DuckDB | `hcm features` | `data/processed/features.parquet` |
| Fit baseline, NB GLM and LightGBM; report metrics | `hcm train` | `data/processed/models/metrics.csv` |
| Export forecasts for the map | `hcm site` | `docs/data/forecasts.json` |

`make all` runs the four in order.

### How a conversion is detected

The BAG has no "conversion" flag. Three patterns are reconstructed from the version history of each verblijfsobject (VBO), each counted once at its first qualifying event ([`src/hcm/conversions.py`](src/hcm/conversions.py)):

1. **use_change** — the VBO's `gebruiksdoel` gains a `woonfunctie` where the previous version had none.
2. **new_unit_in_old_pand** — a residential VBO appears in a pand built ≥ 2 years earlier that previously held only non-residential units (the office-tower-into-apartments case).
3. **after_verbouwing** — residential VBOs appear after the pand passes through the `Verbouwing pand` status.

Totals are reconciled per municipality and year against CBS *transformaties* statistics.

### How the forecast is made

One row per wijk × year ([`sql/features.sql`](sql/features.sql)). Features: non-residential stock by use and build decade, floor area, conversions in the last one and three years here and in adjacent wijken, and lagged CBS indicators. Three models, compared on a strict time split (train ≤ 2022, validate 2023, test 2024):

| Model | Role |
|---|---|
| Seasonal naive (= last year) | The ruler everything is measured against |
| Negative-binomial GLM | Interpretable coefficients; handles over-dispersed counts |
| LightGBM, Tweedie objective, monotone constraints | The forecast on the map |

Metrics: MAE, Poisson deviance, Spearman rank correlation, and **capture@200** — the share of all actual conversions found in the 200 highest-ranked areas, which is what a scouting team with a fixed budget cares about.

### Two things that are easy to get wrong

**No peeking.** Every feature is computed from events the register had *recorded* by the forecast date (`tijdstipRegistratie`), not from when they took effect (`beginGeldigheid`). Municipalities back-date registrations by months; using effective dates would let the model see the future. `tests/test_features.py::test_lag_uses_registration_date_not_event_date` and `features.assert_no_leakage` guard this.

**Boundaries move.** Wijk codes are redrawn and municipalities merge. All BAG history is re-aggregated by coordinate onto one reference vintage of the CBS Wijk- en buurtkaart (`space.reference_year` in `config.yaml`), so only CBS covariates need a crosswalk, weighted by BAG address counts.

## Reproduce

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/housing-conversion-monitor-nl
cd housing-conversion-monitor-nl
python -m venv .venv && source .venv/bin/activate
make install
make test                                   # 20 unit tests, < 5 s

# data (not committed; all open):
#   PDOK  → LV BAG 2.0 full extract         → data/raw/lvbag-extract-nl.zip
#   CBS   → Kerncijfers wijken en buurten   → data/raw/cbs/
#   CBS   → Wijk- en buurtkaart (reference) → data/raw/wijk_2024.gpkg
# then build data/processed/events.parquet with the schema documented in src/hcm/conversions.py

make all
```

The site in `docs/` is static. It reads `docs/data/forecasts.json` and, if present, `docs/data/wijken.geojson` (one feature per wijk with `properties.wijk_code`); without the latter it falls back to a placeholder hex grid so the page always renders.

## Repository layout

```
src/hcm/            package: conversions.py · features.py · model.py · cli.py · config.py
sql/features.sql    the feature table as plain SQL
tests/              detection edge cases, leakage guard, time split
docs/               GitHub Pages site (index.html, app.js, style.css, data/)
config.yaml         paths, years, spatial unit, model settings
Makefile            install · test · detect · features · train · site · all
```

## Data and licences

- Kadaster BAG — [PDOK LV BAG 2.0 extract](https://www.pdok.nl/introductie/-/article/basisregistratie-adressen-en-gebouwen-ba-1), CC0
- CBS Wijk- en buurtkaart and Kerncijfers wijken en buurten, CC BY 4.0
- Code: MIT

## Author

Nathan Chen — PhD in housing economics (University of Groningen), where the conversion detection was developed for research on local housing supply and prices.
