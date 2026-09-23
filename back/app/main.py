"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

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
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.worker import start_agent_worker, stop_agent_worker

log = get_logger(__name__)


def _ensure_zp_conversion_schema_if_enabled() -> None:
    if not settings.zp_management_enabled:
        return
    # Operators may still disable ZP management for legacy/offline fallback.
    from app.zp_conversion.repository import ensure_zp_conversion_schema

    ensure_zp_conversion_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.agent_engineering_enabled and (os.environ.get("VIEWER_ENV") != "test" or settings.agent_api_worker_enabled or len(settings.agent_internal_token or "") < 32):
        raise RuntimeError("Engineering requires an explicitly authorized local test runtime and independent Worker")
    test_trace = os.environ.get("VIEWER_TEST_TRACE_SECONDS") if os.environ.get("VIEWER_ENV") == "test" else None
    if test_trace is not None:
        import faulthandler
        seconds = int(test_trace)
        if not 30 <= seconds <= 300:
            raise RuntimeError("Invalid trusted test trace interval")
        faulthandler.dump_traceback_later(seconds, repeat=True)
    if settings.agent_auto_delivery_enabled:
        from app.agent_import.delivery import require_auto_test_policy
        require_auto_test_policy()  # reject invalid targets before any bootstrap/DDL
    configure_logging()
    log.info("starting proteo-viewer backend (data_root=%s)", settings.resolved_data_root)
    ensure_jobs_table()
    ensure_dataset_fingerprint_schema()
    ensure_runs_metadata_schema()
    _ensure_zp_conversion_schema_if_enabled()
    if settings.agent_import_enabled or settings.agent_revision_reads_enabled:
        ensure_agent_import_schema()
    start_agent_worker()
    try:
        yield
    finally:
        stop_agent_worker()
        if test_trace is not None:
            faulthandler.cancel_dump_traceback_later()


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
    result = {"status": "ok"}
    if settings.viewer_build_id:
        result["build_id"] = settings.viewer_build_id
    if settings.viewer_validation_id:
        result["validation_id"] = settings.viewer_validation_id
    return result
