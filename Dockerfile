# Runs the full pipeline on the synthetic sample (or on real staging data mounted at /app/data).
#   docker build -t hcm .
#   docker run --rm -v $PWD/data:/app/data hcm hcm pipeline
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgdal-dev gdal-bin make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[geo,quality,orchestration,dbt]"
COPY . .
RUN hcm sample
CMD ["hcm", "pipeline"]
