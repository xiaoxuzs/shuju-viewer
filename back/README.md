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

# 2. Create tables (universal 7-table schema)
psql -h localhost -U postgres -d Universal_Viewer -f ..\docs\universal_schema.sql

# 3. Ingest a dataset
uv run python -m app.ingest.universal_toppic_adapter ingest `
    --root ..\shuju\MZ20160222DS_histone48_html `
    --database-url "postgresql+psycopg://postgres:postgres@localhost:5432/Universal_Viewer" `
    --slug mz20160222ds_histone48 `
    --name "MZ20160222DS_histone48" `
    --mode full --replace

# 4. Start API
uv run uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for the OpenAPI UI.

## Offline Bottom-Up coverage

Bottom-Up protein Sequence Coverage is offline by default:

```powershell
BU_UNIPROT_ENABLED=false
```

With this setting, protein detail pages never call UniProt. Coverage uses an
existing `proteins.base_sequence` value or a single `*.fasta` / `*.fa` file
placed anywhere under the dataset `source_root` (for example
`reference/uniprot_human.fasta`). If no local sequence is available, the API
returns `coverage_mode: "list_only"` and still shows the peptide table.

Set `BU_UNIPROT_ENABLED=true` only when the deployment is allowed to lazily
fetch `https://rest.uniprot.org/uniprotkb/{accession}.fasta`.

## Project layout

```
app/
  core/        config, database session, logging
  schemas/     Pydantic request/response schemas
  services/    background import jobs, spectrum cache
  ingest/      universal-schema TopPIC/TopFD adapter (CLI + library)
  api/v1/      REST routes (raw SQL against the universal schema)
```

The on-disk database schema is owned by `docs/universal_schema.sql`. Reads go
through `app/api/v1/*.py` + `app/api/v1/universal_compat.py`; writes (both path
upload via `POST /api/v1/imports` and the CLI above) go through
`app/ingest/universal_toppic_adapter.py`. There is no SQLAlchemy ORM layer or
Alembic migration tree anymore — that has been removed in favour of the single
universal schema.
