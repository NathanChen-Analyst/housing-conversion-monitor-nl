# Orchestration (Dagster)

```bash
pip install -e ".[orchestration]"
dagster dev -f orchestration/definitions.py                       # UI at http://localhost:3000
dagster asset materialize -f orchestration/definitions.py --select '*'
```

Assets, in order: `vbo_versions` (idempotent mutation ingest) → `stock_snapshots` → `conversion_events`
(production detector if `hcm_private` is installed, else illustrative) → `events_located` → `wijk_year`
(suppression, public files) → `quality_report` → `forecast` (placeholder).
Two asset checks guard the silver and the publish layer; a monthly schedule follows PDOK's release cadence.
Every step appends a line to `runs/runs.jsonl` with its duration and row counts.
