"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services.import_jobs import (
    ensure_dataset_fingerprint_schema,
    ensure_jobs_table,
    ensure_runs_metadata_schema,
)

log = get_logger(__name__)


def _ensure_zp_conversion_schema_if_enabled() -> None:
    if not settings.zp_management_enabled:
        return
    # Keep ZP bootstrap behind the management flag so default server startup
    # does not require permissions for optional ZP tables.
    from app.zp_conversion.repository import ensure_zp_conversion_schema

    ensure_zp_conversion_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("starting proteo-viewer backend (data_root=%s)", settings.resolved_data_root)
    ensure_jobs_table()
    ensure_dataset_fingerprint_schema()
    ensure_runs_metadata_schema()
    _ensure_zp_conversion_schema_if_enabled()
    yield


app = FastAPI(
    title="proteo-viewer API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
