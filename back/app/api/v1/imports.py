"""Dataset import from a server-side folder path (background ingest job)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.schemas.imports import ImportEnqueueIn, ImportJobCreatedOut, ImportJobOut
from app.services import import_jobs
from app.dataset_ingest_root import resolve_ingest_root

router = APIRouter(tags=["imports"])


@router.post("/imports", response_model=ImportJobCreatedOut, status_code=status.HTTP_202_ACCEPTED)
def enqueue_import(body: ImportEnqueueIn) -> ImportJobCreatedOut:
    raw = body.source_path.strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="source_path is required.")

    try:
        p = Path(raw).expanduser()
        if not p.exists():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Path does not exist: {raw}")
        if not p.is_dir():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Path is not a directory: {raw}")
        resolved = str(p.resolve())
        # Fail fast if the tree is unusable (nested root resolution).
        resolve_ingest_root(p)
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
    import_jobs.start_path_import_background(
        job_id=job.job_id,
        source_path=resolved,
        slug=body.slug.strip(),
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
    )
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
