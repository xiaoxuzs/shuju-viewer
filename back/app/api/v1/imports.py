"""Dataset import from uploaded ZIP (unpack under ``shuju``, then ingest).

The uploaded archive is streamed to a temp file (no full-buffer read) before
the background ingest job touches the database. State is persisted in the
``import_jobs`` table so the frontend can keep polling across reloads.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.schemas.imports import ImportJobCreatedOut, ImportJobOut
from app.services import import_jobs
from app.services.zip_source_fingerprint import sha256_hex_of_file

router = APIRouter(tags=["imports"])


@router.post("/imports", response_model=ImportJobCreatedOut, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_import(
    file: UploadFile = File(..., description="ZIP of a TopPIC output folder (topfd + toppic_*_cutoff)."),
    slug: str = Form(..., description="Unique slug for URLs (e.g. mz20160222ds_histone48)."),
    name: str = Form(..., description="Human-readable dataset name."),
    description: str | None = Form(None),
) -> ImportJobCreatedOut:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Upload a .zip archive containing one TopPIC dataset folder.",
        )

    suffix = Path(file.filename).suffix or ".zip"
    zip_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="viewer-import-", suffix=suffix, delete=False) as tf:
            shutil.copyfileobj(file.file, tf, length=1024 * 1024)  # 1 MiB chunks
            zip_path = Path(tf.name)
        if zip_path.stat().st_size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    except HTTPException:
        if zip_path is not None:
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    except Exception as exc:  # noqa: BLE001
        if zip_path is not None:
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:  # noqa: BLE001
            pass

    if zip_path is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store upload; retry.",
        )
    zip_sha256_hex = sha256_hex_of_file(zip_path)
    dup = import_jobs.find_dataset_with_zip_sha256(zip_sha256_hex)
    if dup is not None:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "This ZIP has already been imported as an existing dataset. Delete that dataset first to re-import, or upload a different archive.",
                "slug": dup.slug,
                "dataset_name": dup.dataset_name,
            },
        )

    job = import_jobs.create_job(
        slug=slug.strip(),
        name=name.strip(),
        description=description.strip() if description else None,
        source_zip_name=file.filename,
    )
    import_jobs.start_zip_import_background(
        job_id=job.job_id,
        zip_path=zip_path,
        slug=slug.strip(),
        name=name.strip(),
        description=description.strip() if description else None,
        source_zip_sha256_hex=zip_sha256_hex,
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
