.PHONY: install test lint detect features train site all clean

PY ?= python

install:
	$(PY) -m pip install -e ".[dev,geo,explain]"

test:
	$(PY) -m pytest -q

lint:
	ruff check src tests

detect:        ## detect conversions from data/processed/events.parquet
	hcm detect

features:      ## build wijk × year feature table
	hcm features

train:         ## fit baseline / NB GLM / LightGBM and print metrics
	hcm train

site:          ## export forecasts.json for the docs/ map
	hcm site

all: detect features train site

clean:
	rm -rf data/processed/*.parquet data/processed/models docs/data/forecasts.json
