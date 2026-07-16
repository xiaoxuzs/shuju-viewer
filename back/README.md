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

# 2. Create tables (universal 8-table schema)
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
`reference/uniprot_human.fasta`). New Bottom-Up imports automatically backfill
`proteins.base_sequence` from that unique FASTA when it exists. Existing
datasets can be backfilled without re-importing matches:

```powershell
cd back
uv run python scripts/backfill_bu_protein_sequences.py --slug bu_pr1_dia
```

If no local sequence is available, or if more than one FASTA is found under the
ingest root, the API returns `coverage_mode: "list_only"` and still shows the
peptide table.

Set `BU_UNIPROT_ENABLED=true` only when the deployment is allowed to lazily
fetch `https://rest.uniprot.org/uniprotkb/{accession}.fasta`.

## Bruker `.d` runtime support

Bottom-Up datasets with Bruker `.d` runs use the optional `tdfpy` reader for
run-level TIC/BPC chromatograms, DIA isolation windows, and the match-level
m/z by ion-mobility slice. Install the optional group on hosts that need these
views:

```powershell
cd back
uv sync --group bruker
```

The run `file_path` or `run_metadata.tdf_path` must point to a readable Bruker
TDF root containing `analysis.tdf` and `analysis.tdf_bin`. This does not enable
Bruker match-level MS2 or XIC; v1 still returns `unsupported_raw_format` for
those endpoints.

## Bottom-Up delivery notes

The sample data package README at `D:\dia-shuju\README.md` has a Viewer
handoff section with the exact local URLs, the `bu_pr1_dia` slug, FASTA
backfill steps for offline Sequence Coverage, and Bruker `.d` setup notes.

The checked acceptance record for the Bottom-Up Viewer handoff lives in
`..\docs\BU-ACCEPTANCE.md`. Re-run the commands in that file before cutting a
release or sharing a new machine setup.

## Project layout

```
app/
  core/        config, database session, logging
  schemas/     Pydantic request/response schemas
  services/    background import jobs, spectrum cache
  ingest/      universal-schema TopPIC/TopFD adapter (CLI + library)
  api/v1/      REST routes (raw SQL against the universal schema)
```

Empty-database initialization is owned by the 8-table `docs/universal_schema.sql`
snapshot. Versioned incremental SQL and the legacy Catalog baseline live in
`back/migrations/` and are operated explicitly with `python -m
app.schema_migrations`; application startup is not switched to this gate until
P2-2B2. Reads go
through `app/api/v1/*.py` + `app/api/v1/universal_compat.py`; writes (both path
upload via `POST /api/v1/imports` and the CLI above) go through
`app/ingest/universal_toppic_adapter.py`. There is no complete SQLAlchemy ORM
metadata or Alembic migration tree; the explicit migration runner uses psycopg
and PostgreSQL Catalog data directly.
