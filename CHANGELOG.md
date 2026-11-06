# Changelog

## 0.2.0 — 2026-11-06
- Layered storage (raw / staging / marts) and `docs/data-model.md` (SCD2 model, as-of vs as-known snapshots)
- `hcm.staging`: point-in-time snapshots over the BAG version history; Hive-partitioned yearly stock
- `hcm.mutations`: idempotent merge of PDOK monthly mutation files with an applied-files ledger
- `hcm.quality`: pandera schemas per layer, SCD2 invariants, disclosure-rule check, CBS reconciliation, HTML report
- dbt project on DuckDB (staging → intermediate → marts) with 21 schema tests
- Dagster asset graph with two asset checks and a monthly schedule; run metadata in `runs/runs.jsonl`
- Synthetic BAG-like sample so the whole pipeline runs in CI and in Docker without the real extract
- `hcm` CLI: sample · ingest · snapshot · quality · pipeline

## 0.1.0 — 2026-11-05
- Office-to-housing conversion map (wijk × year, 2012–2024) on GitHub Pages
- Public aggregation with small-cell suppression; README graphic rendered from the same data
