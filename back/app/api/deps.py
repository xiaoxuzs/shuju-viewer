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
    if settings.agent_revision_reads_enabled and slug:
        if request.method not in {"GET", "HEAD"}:
            raise HTTPException(409, detail={"code": "REVISION_WRITE_REQUIRES_CANDIDATE", "message": "Published revisions are immutable; prepare a new candidate."})
        from app.core.db import engine
        from app.agent_import.revisions import RevisionStore
        from app.agent_import.errors import AgentImportError
        store = RevisionStore(engine, settings.resolved_zp_output_root / "revisions", build_sha256=settings.viewer_build_id or "", signing_key=(settings.agent_verification_signing_key or "").encode())
        try:
            revision = store.resolve(slug, request.headers.get("x-viewer-revision"))
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
