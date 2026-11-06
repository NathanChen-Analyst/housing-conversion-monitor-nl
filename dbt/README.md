# dbt models (DuckDB)

Local, no warehouse needed:

```bash
cd dbt
dbt build --profiles-dir .          # run + test every model against data/staging
dbt docs generate --profiles-dir .  # lineage graph and column docs in target/
```

Layers: `staging` (views over the Parquet silver layer, dedup + parsed flags) → `intermediate`
(1-January stock snapshots; conversion events) → `marts` (yearly series, registration-lag profile).
Tests: uniqueness of every grain, not-null keys, accepted status values, non-negative counts.

The intermediate detector here is the illustrative one; the production detector is private until
publication and materialises the same `int_conversion_events` grain.
