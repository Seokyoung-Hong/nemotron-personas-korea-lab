# Nemotron Personas Korea Lab

A lightweight DuckDB + FastAPI web app for exploring the public NVIDIA/Hugging Face `nvidia/Nemotron-Personas-Korea` dataset and turning synthetic personas into **customer-discovery hypotheses**.

This repository intentionally contains **code only**. It does **not** include the dataset, generated DuckDB files, exports, local interview notes, or private project-specific business context.

## What this is for

- Load the Korea persona Parquet shards into DuckDB views.
- Explore demographic, occupation, region, and food/lifestyle persona text.
- Generate generic workplace-meal/customer-discovery segments.
- Record validation results from real interviews or field experiments.
- Use a three-pane OpenWebUI-style interface: segment sidebar, chat-like exploration, and hypothesis inspector.

## Important limitation

Synthetic personas are useful for ideation, but they are **not evidence of real demand**. Use them to create hypotheses, then validate with real interviews, surveys, or field tests.

## Dataset

Download the dataset separately:

```bash
hf download nvidia/Nemotron-Personas-Korea \
  --repo-type dataset \
  --local-dir ./data \
  --max-workers 4
```

Expected layout:

```text
data/
  README.md
  data/train-00000-of-00009.parquet
  ...
  data/train-00008-of-00009.parquet
```

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Build the DuckDB metadata/views

```bash
python scripts/create_duckdb.py --dataset-dir ./data --db-path ./db/nemotron_personas_ko.duckdb
python scripts/create_segments.py --db-path ./db/nemotron_personas_ko.duckdb
```

The default design keeps the original Parquet files outside the database and creates DuckDB views over them, avoiding a large duplicate materialized copy.

## Run the web app

```bash
python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8787
```

Open:

```text
http://localhost:8787/
```

For a non-local deployment, set:

```bash
export PERSONA_LAB_DB=/absolute/path/to/db/nemotron_personas_ko.duckdb
```

## API

```text
GET  /api/health
GET  /api/summary
GET  /api/segments
GET  /api/personas?segment_id=...&q=점심&province=경기&limit=20
GET  /api/hypotheses?segment_id=...
POST /api/workspaces
GET  /api/validation-results?hypothesis_id=...
POST /api/validation-results
```

## Tests

```bash
pytest tests -q
```

The tests use a tiny fixture database and do not require the full dataset.

## Privacy and publishing notes

- Do not commit raw Parquet shards or generated exports.
- Do not commit `.env`, tokens, interview notes, or private business context.
- Keep the repository generic; put project-specific hypotheses and validation notes in a private system.
