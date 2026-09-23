"""Management API for server-side ZP conversion jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.zp_conversions import (
    ZpAssetOut,
    ZpConversionCreatedOut,
    ZpConversionCreateIn,
    ZpConversionJobOut,
    ZpDatasetStatusOut,
    ZpExtensionListOut,
    ZpExtensionPayloadOut,
    ZpExtensionSummaryOut,
)
from app.zp_conversion.contracts import ZpArtifact, ZpConversionError, ZpConversionJob
from app.zp_conversion.service import (
    cancel_conversion,
    enqueue_conversion,
    get_conversion_job,
    latest_dataset_job,
    list_dataset_assets,
)
from app.zp_runtime import ZpAssetReadError, get_binary_extension_payload, get_binary_extension_summaries

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


@router.get("/datasets/{dataset_id}/binary-extensions", response_model=ZpExtensionListOut)
def list_dataset_binary_extensions(
    dataset_id: int,
    session: Session = Depends(get_db),
) -> ZpExtensionListOut:
    try:
        summaries = get_binary_extension_summaries(session, dataset_id)
    except ZpAssetReadError as exc:
        raise _binary_read_error(exc) from exc
    if summaries is None:
        raise _binary_not_found()
    return ZpExtensionListOut(
        dataset_id=dataset_id,
        extensions=[
            ZpExtensionSummaryOut(
                extension_type=summary.extension_type,
                extension_version=summary.extension_version,
                owner=summary.owner,
                schema_name=summary.schema_name,
                schema_version=summary.schema_version,
                record_count=summary.record_count,
            )
            for summary in summaries
        ],
    )


@router.get("/datasets/{dataset_id}/binary-extensions/{extension_type}", response_model=ZpExtensionPayloadOut)
def get_dataset_binary_extension(
    dataset_id: int,
    extension_type: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> ZpExtensionPayloadOut:
    try:
        extension = get_binary_extension_payload(session, dataset_id, extension_type)
    except ZpAssetReadError as exc:
        if str(exc) == "binary_extension_not_found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="binary_extension_not_found") from exc
        raise _binary_read_error(exc) from exc
    if extension is None:
        raise _binary_not_found()

    payload = _paged_payload(extension.payload, offset=offset, limit=limit)
    return ZpExtensionPayloadOut(
        dataset_id=dataset_id,
        extension_type=extension.extension_type,
        extension_version=extension.extension_version,
        owner=payload.get("owner") if isinstance(payload.get("owner"), str) else None,
        schema_name=payload.get("schema_name") if isinstance(payload.get("schema_name"), str) else None,
        schema_version=payload.get("schema_version"),
        record_count=payload.get("record_count") if isinstance(payload.get("record_count"), int) else None,
        offset=offset,
        limit=limit,
        returned_record_count=payload.pop("_returned_record_count", None),
        payload=payload,
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


def _binary_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="binary_asset_not_found")


def _binary_read_error(exc: ZpAssetReadError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


def _paged_payload(payload: dict[str, Any], *, offset: int, limit: int) -> dict[str, Any]:
    out = dict(payload)
    records = out.get("records")
    if isinstance(records, list):
        out["_returned_record_count"] = len(records[offset : offset + limit])
        out["records"] = records[offset : offset + limit]
    return out
