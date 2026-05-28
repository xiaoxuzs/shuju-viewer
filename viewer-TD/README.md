# viewer-TD

Top-Down-only slice of the proteo-viewer stack (PrSM spectrum browsing).

## One-click launch (Windows)

1. **First time only:** double-click `prepare-launch.bat` (installs deps and builds `front/dist`).
2. **Every time:** double-click `Launch.bat` — starts the server on port **7000** and opens your default browser.

The packaged mode serves the built UI from the same port as the API (`http://127.0.0.1:7000/`), so no separate frontend process is needed.

Requirements on the machine: **PostgreSQL** (database `viewer-td`), **Python 3.12+** with `uv`, and **Node.js + pnpm** (only for `prepare-launch.bat`).

## Dev mode (separate frontend + backend)

**Recommended — double-click:**

| Script | Purpose |
|--------|---------|
| `dev-all.bat` | Open **two windows**: backend + frontend |
| `dev-back.bat` | Backend only (`7000`, hot reload) |
| `dev-front.bat` | Frontend only (`6100`, Vite dev server) |
| `dev-stop.bat` | Stop processes on ports **7000** and **6100** |

| Service  | URL |
|----------|-----|
| Frontend | http://localhost:6100 |
| Backend  | http://localhost:7000/docs |

> Chrome blocks port **6000** (`ERR_UNSAFE_PORT`); dev server uses **6100** instead.

Legacy scripts `start-all.bat` / `start-back.bat` still work; prefer `dev-*.bat` for clearer window titles.

## First-time setup

```powershell
# Database (PostgreSQL)
psql -h localhost -U postgres -c 'CREATE DATABASE "viewer-td";'
psql -h localhost -U postgres -d viewer-td -f docs\universal_schema.sql

# Backend
cd back
Copy-Item .env.example .env   # edit DATABASE_URL if needed
uv sync
uv run uvicorn app.main:app --reload --port 7000

# Frontend (new terminal)
cd front
pnpm install
pnpm dev
```

Or from this folder: `start-all.bat`

## Data

Imported datasets are stored under `shuju/` (see `DATA_ROOT` in `back/.env`).


