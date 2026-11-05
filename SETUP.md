# Putting this on GitHub and online (one-time, ~10 minutes)

## 0. Placeholder

Already replaced with `NathanChen-Analyst` everywhere. Nothing to do.

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

## 4. Updating the data later

Re-run `conversion_export.run(...)` (and `add_wijk_names(...)`) on the cluster, download the two files
`wijk_year_conversions.json` and `wijken.geojson` into `docs/data/`, commit, push. Pages redeploys by itself.

## 5. Optional polish

- Add a screenshot of the live map at the top of the README (`docs/screenshot.png`).
- Pin the repository on your GitHub profile.
- Put the Pages URL in the repository's *About* box (top right of the repo page).
