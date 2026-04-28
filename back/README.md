# proteo-viewer Backend

**中文说明：** [README.zh-CN.md](README.zh-CN.md)

FastAPI + SQLAlchemy + PostgreSQL backend for browsing histone proteomics result bundles
(TopPIC / TopFD outputs).

## Quick Start

Requires `uv` and a running PostgreSQL 14+.

```powershell
# From the repo root (viewer/)
cd back
uv sync

# 1. Configure connection (edit .env if different from defaults)
Copy-Item .env.example .env -ErrorAction SilentlyContinue

# 2. Create tables
uv run alembic upgrade head

# 3. Ingest a dataset
uv run python -m app.ingest.cli ingest `
    --root ..\shuju\MZ20160222DS_histone48_html `
    --slug mz20160222ds_histone48 `
    --name "MZ20160222DS_histone48"

# 4. Start API
uv run uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for the OpenAPI UI.

## Project layout

```
app/
  core/        config, database session, logging
  models/      SQLAlchemy ORM entities
  schemas/     Pydantic request/response schemas
  services/    business logic, spectrum caching
  ingest/      dataset import pipeline (JS -> DB)
  api/v1/      REST routes
alembic/       database migrations
```
