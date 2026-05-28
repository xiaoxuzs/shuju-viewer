"""Dataset import from a server-side folder path (background ingest job)."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.imports import ImportEnqueueIn, ImportJobCreatedOut, ImportJobOut, ImportPickFolderOut
from app.services import import_jobs
from app.services.native_folder_dialog import NativeFolderDialogError, pick_folder_native
from app.dataset_ingest_root import resolve_ingest_root
from app.toppic_admission import classify_admission

router = APIRouter(tags=["imports"])
log = get_logger(__name__)

_ENQUEUE_TIMING_ORDER: tuple[str, ...] = (
    "enqueue_path_checks_s",
    "enqueue_resolve_ingest_root_s",
    "enqueue_create_job_s",
    "enqueue_total_s",
)


def _client_is_loopback(request: Request) -> bool:
    c = request.client
    if not c or not c.host:
        return False
    h = c.host.lower()
    return h in ("127.0.0.1", "::1") or h.startswith("127.") or h.endswith("127.0.0.1")


@router.post("/imports/pick-folder", response_model=ImportPickFolderOut)
def pick_import_folder(request: Request) -> ImportPickFolderOut:
    """Open a native folder dialog on the **API host** and return the chosen absolute path.

    Intended for local development where the browser and FastAPI run on the same desktop.
    """
    if not settings.import_native_folder_picker:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Native folder picker is disabled (set IMPORT_NATIVE_FOLDER_PICKER=true to enable).",
        )
    if settings.import_picker_loopback_only and not _client_is_loopback(request):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Native folder picker is only allowed for requests from localhost.",
        )
    try:
        chosen_path, cancelled = pick_folder_native()
    except NativeFolderDialogError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if cancelled or not chosen_path:
        return ImportPickFolderOut(cancelled=True)
    return ImportPickFolderOut(path=chosen_path)


@router.post("/imports", response_model=ImportJobCreatedOut, status_code=status.HTTP_202_ACCEPTED)
def enqueue_import(body: ImportEnqueueIn) -> ImportJobCreatedOut:
    raw = body.source_path.strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="source_path is required.")

    enqueue_t0 = time.perf_counter()
    enqueue_t = enqueue_t0
    enqueue_timing: dict[str, float] = {}

    def _enqueue_slice(label: str) -> None:
        nonlocal enqueue_t
        now = time.perf_counter()
        enqueue_timing[label] = now - enqueue_t
        enqueue_t = now

    try:
        p = Path(raw).expanduser()
        if not p.exists():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Path does not exist: {raw}")
        if not p.is_dir():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Path is not a directory: {raw}")
        resolved = str(p.resolve())
        _enqueue_slice("enqueue_path_checks_s")
        # Fail fast if the tree is unusable (nested root resolution).
        ingest_root = resolve_ingest_root(p)
        _enqueue_slice("enqueue_resolve_ingest_root_s")
        decision = classify_admission(ingest_root)
        if not decision.is_supported:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=decision.reject_reason)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job = import_jobs.create_job(
        slug=body.slug.strip(),
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        source_path=resolved,
    )
    _enqueue_slice("enqueue_create_job_s")

    import_jobs.start_path_import_background(
        job_id=job.job_id,
        source_path=resolved,
        slug=body.slug.strip(),
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
    )

    enqueue_timing["enqueue_total_s"] = time.perf_counter() - enqueue_t0
    timing_parts = " ".join(
        f"{key}={enqueue_timing[key]:.3f}"
        for key in _ENQUEUE_TIMING_ORDER
        if key in enqueue_timing
    )
    log.info("enqueue_timing job_id=%s %s", job.job_id, timing_parts)

    return ImportJobCreatedOut(job_id=job.job_id, status="queued")


@router.get("/imports/{job_id}", response_model=ImportJobOut)
def get_import_job(job_id: str) -> ImportJobOut:
    job = import_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown import job.")
    return ImportJobOut(
        job_id=job.job_id,
        status=job.status,
        message=job.message,
        error=job.error,
        dataset_slug=job.dataset_slug,
        progress=job.progress,
        stage=job.stage,
        stage_label=job.stage_label,
        stage_detail=job.stage_detail,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
