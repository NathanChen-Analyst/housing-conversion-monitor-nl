.PHONY: install test lint sample pipeline quality dbt dagster site clean

PY ?= python

install:          ## everything needed for the full pipeline
	$(PY) -m pip install -e ".[all]"

test:
	$(PY) -m pytest -q

lint:
	ruff check src tests orchestration scripts

sample:           ## synthetic BAG-like data so the pipeline runs without the real extract
	hcm sample

pipeline:         ## materialise every Dagster asset once
	hcm pipeline

quality:          ## data-quality report → docs/quality.html
	hcm quality

dbt:              ## dbt build (models + tests) on DuckDB
	cd dbt && dbt build --profiles-dir .

dagster:          ## Dagster UI at http://localhost:3000
	dagster dev -f orchestration/definitions.py

site:             ## export public JSON for the map from the real events table
	hcm site

clean:
	rm -rf data/marts data/staging data/raw/mutations data/raw/buurt_sample.gpkg runs dbt/target docs/quality.html
