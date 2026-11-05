# Putting this on GitHub and online (one-time, ~10 minutes)

## 0. Replace the placeholder

Search the repo for `YOUR_GITHUB_USERNAME` and replace it with your GitHub username. It appears in `README.md` and `docs/index.html`.

```bash
grep -rl YOUR_GITHUB_USERNAME . | xargs sed -i 's/YOUR_GITHUB_USERNAME/<your-username>/g'
```

(macOS: `sed -i ''` instead of `sed -i`.)

## 1. Create the repository on GitHub

github.com → **New repository** → name `housing-conversion-monitor-nl` → Public → **do not** add a README, .gitignore or licence (they are already here) → Create.

## 2. Push

```bash
cd housing-conversion-monitor-nl
git init -b main
git add .
git commit -m "Scaffold: conversion detection, feature SQL, models, tests, Pages site"
git remote add origin https://github.com/<your-username>/housing-conversion-monitor-nl.git
git push -u origin main
```

The CI workflow runs on this first push; the badge in the README turns green when tests pass.

## 3. Turn on GitHub Pages

Repository → **Settings** → **Pages** → under *Build and deployment*:
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/docs** → Save.

After one or two minutes the site is live at
`https://<your-username>.github.io/housing-conversion-monitor-nl/`

Every later `git push` that touches `docs/` redeploys automatically.

## 4. Replace the placeholder data with real output

1. Produce `data/processed/events.parquet` from your thesis pipeline (schema in `src/hcm/conversions.py`).
2. `make all` → writes `docs/data/forecasts.json`.
3. Export the reference wijk boundaries as GeoJSON in WGS84 with a `wijk_code` property, e.g. with GeoPandas:
   ```python
   gdf = gpd.read_file("data/raw/wijk_2024.gpkg").to_crs(4326)
   gdf = gdf.rename(columns={"WK_CODE": "wijk_code", "WK_NAAM": "name"})[["wijk_code", "name", "geometry"]]
   gdf.geometry = gdf.geometry.simplify(0.0005)          # keeps the file small
   gdf.to_file("docs/data/wijken.geojson", driver="GeoJSON")
   ```
4. In `docs/data/forecasts.json`, `hcm site` sets `meta.synthetic` to false and fills `meta.headline` from `metrics.csv`; the "Prototype" pill disappears.
5. Commit and push. Done.

## 5. Optional polish

- Add a screenshot of the live map at the top of the README (`docs/screenshot.png`).
- Pin the repository on your GitHub profile.
- Put the Pages URL in the repository's *About* box (top right of the repo page).
