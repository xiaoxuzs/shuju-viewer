"""Management API for server-side ZP conversion jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.zp_conversions import (
    ZpAssetOut,
    ZpConversionCreatedOut,
    ZpConversionCreateIn,
    ZpConversionJobOut,
    ZpDatasetStatusOut,
)
from app.zp_conversion.contracts import ZpArtifact, ZpConversionError, ZpConversionJob
from app.zp_conversion.service import (
    cancel_conversion,
    enqueue_conversion,
    get_conversion_job,
    latest_dataset_job,
    list_dataset_assets,
)

router = APIRouter(tags=["zp-conversions"])


@router.post("/zp-conversions", response_model=ZpConversionCreatedOut, status_code=status.HTTP_202_ACCEPTED)
def create_zp_conversion(body: ZpConversionCreateIn) -> ZpConversionCreatedOut:
    try:
        job = enqueue_conversion(
            source_path=body.source_path,
            dataset_slug=body.dataset_slug,
            format_version=body.format_version,
        )
    except ZpConversionError as exc:
        raise _http_error(exc) from exc
    return ZpConversionCreatedOut(job_id=job.job_id, status=job.status)


@router.get("/zp-conversions/{job_id}", response_model=ZpConversionJobOut)
def get_zp_conversion(job_id: str) -> ZpConversionJobOut:
    job = get_conversion_job(job_id)
    if job is None:
        raise _not_found()
    return _job_out(job)


@router.post("/zp-conversions/{job_id}/cancel", response_model=ZpConversionJobOut)
def cancel_zp_conversion(job_id: str) -> ZpConversionJobOut:
    job = cancel_conversion(job_id)
    if job is None:
        raise _not_found()
    return _job_out(job)


@router.get("/datasets/{dataset_id}/zp-status", response_model=ZpDatasetStatusOut)
def get_dataset_zp_status(dataset_id: int, dataset_slug: str | None = None) -> ZpDatasetStatusOut:
    assets = list_dataset_assets(dataset_id)
    latest_job = latest_dataset_job(dataset_slug)
    active_assets = [asset for asset in assets if asset.status == "active"]
    return ZpDatasetStatusOut(
        dataset_id=dataset_id,
        has_active_zp=bool(active_assets),
        active_asset_count=len(active_assets),
        assets=[_asset_out(asset) for asset in assets],
        latest_job=_job_out(latest_job) if latest_job is not None else None,
    )


def _job_out(job: ZpConversionJob) -> ZpConversionJobOut:
    return ZpConversionJobOut(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        dataset_slug=job.dataset_slug,
        format_version=job.format_version,
        input_bytes=job.input_bytes,
        output_bytes=job.output_bytes,
        output_sha256=job.output_sha256,
        validation_mode=job.validation_mode,
        error_code=job.error_code,
        error_message=job.public_error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
    )


def _asset_out(asset: ZpArtifact) -> ZpAssetOut:
    return ZpAssetOut(
        asset_id=asset.asset_id,
        dataset_id=asset.dataset_id,
        run_id=asset.run_id,
        format_version=asset.format_version,
        output_sha256=asset.output_sha256,
        status=asset.status,
        capabilities=asset.capabilities,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _http_error(exc: ZpConversionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _not_found() -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={"code": "ZP_JOB_NOT_FOUND", "message": "ZP conversion job was not found."},
    )
