"""Shared FastAPI dependencies.

Only ``get_db`` is used by the v1 routes; the ORM-based ``get_dataset`` /
``get_cutoff`` helpers were removed together with the legacy ORM models since
the API now reads from the universal 7-table schema directly via ``text()``.
Slug / cutoff validation lives in :mod:`app.api.v1.universal_compat`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from fastapi import Request, Response, HTTPException

from app.core.db import get_session


def get_db(request: Request = None, response: Response = None) -> Session:  # type: ignore[return-value]
    from app.core.config import settings
    slug = request.path_params.get("slug") if request is not None else None
    if settings.agent_revision_reads_enabled and request is not None and not slug and request.path_params.get("dataset_id"):
        from app.core.db import engine
        from sqlalchemy import text
        with engine.connect() as db:
            slug = db.execute(text("SELECT slug FROM datasets WHERE dataset_id=:id"), {"id": request.path_params["dataset_id"]}).scalar()
    if settings.agent_revision_reads_enabled and slug:
        from app.core.db import engine
        from app.agent_import.maintenance_publication import revision_store
        from app.agent_import.errors import AgentImportError
        store = revision_store(engine)
        try:
            revision = store.resolve(slug, request.headers.get("x-viewer-revision"))
            if revision and request.method not in {"GET", "HEAD"}:
                raise HTTPException(409, detail={"code": "REVISION_WRITE_REQUIRES_CANDIDATE", "message": "Published revisions are immutable; prepare a new candidate."})
            if response is not None:
                response.headers["X-Viewer-Revision"] = revision or "legacy"
                response.headers["Cache-Control"] = "private, no-store"
            if revision:
                with store.projection(revision) as session:
                    yield session
                return
        except AgentImportError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    yield from get_session()
