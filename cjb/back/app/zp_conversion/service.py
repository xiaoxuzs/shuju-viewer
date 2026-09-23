"""Service layer for managed .zp conversion jobs."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.zp_conversion import process_control
from app.zp_conversion.contracts import ZpArtifact, ZpConversionError, ZpConversionJob
from app.zp_conversion.paths import cleanup_job_paths, input_size_bytes, prepare_job_paths, resolve_source_path
from app.zp_conversion.repository import (
    create_job,
    dataset_id_for_slug,
    get_job,
    latest_job_for_dataset_slug,
    list_assets_for_dataset,
    register_asset,
    request_cancel,
    update_job,
)
from app.zp_conversion.worker_runner import (
    WorkerExecutionError,
    WorkerRequest,
    ZpWorkerRunner,
    default_worker_runner,
)

log = get_logger(__name__)


def enqueue_conversion(
    *,
    source_path: str | Path,
    dataset_slug: str | None = None,
    format_version: int | None = None,
    start_background: bool = True,
    runner: ZpWorkerRunner | None = None,
) -> ZpConversionJob:
    source = resolve_source_path(source_path)
    selected_version = format_version or settings.zp_default_format_version
    if selected_version not in {1, 2, 3}:
        raise ZpConversionError("ZP_INTERNAL_ERROR")
    job_id = str(uuid.uuid4())
    paths = prepare_job_paths(job_id)
    job = create_job(
        job_id=job_id,
        source_path=source,
        dataset_slug=_clean_slug(dataset_slug),
        paths=paths,
        format_version=selected_version,
        input_bytes=input_size_bytes(source),
    )
    if start_background:
        start_conversion_background(job.job_id, runner=runner)
    return job


def start_conversion_background(job_id: str, *, runner: ZpWorkerRunner | None = None) -> None:
    thread = threading.Thread(
        target=run_conversion_job,
        kwargs={"job_id": job_id, "runner": runner},
        name=f"zp-conversion-{job_id}",
        daemon=True,
    )
    thread.start()


def run_conversion_job(job_id: str, *, runner: ZpWorkerRunner | None = None) -> ZpConversionJob | None:
    job = get_job(job_id)
    if job is None:
        return None
    if job.status == "cancelling":
        _mark_cancelled(job)
        return get_job(job_id)
    if job.status != "queued":
        return job

    update_job(job_id, status="running", stage="inspect", progress=1.0, error_code=None, error_message=None)
    current = get_job(job_id)
    if current is None:
        return None
    try:
        request = _worker_request(current)
        selected_runner = runner or default_worker_runner()

        def report_progress(stage: str, progress: float, _message: str | None = None) -> None:
            update_job(job_id, stage=stage, progress=max(0.0, min(99.0, progress)))

        result = selected_runner.run(request, report_progress)
        update_job(
            job_id,
            status="success",
            stage="success",
            progress=100.0,
            output_bytes=result.output_bytes,
            output_sha256=result.output_sha256,
            validation_mode=result.validation_mode,
            binary_layer_version=result.binary_layer_version,
        )
        _register_success_asset(get_job(job_id))
        cleanup_job_paths(temp_dir=request.temp_dir, partial_path=request.partial_path)
    except WorkerExecutionError as exc:
        refreshed = get_job(job_id)
        if refreshed is not None and refreshed.status in {"cancelling", "cancelled"}:
            _mark_cancelled(refreshed)
        else:
            _mark_failed(job_id, exc.code)
    except Exception:  # noqa: BLE001
        log.exception("ZP conversion job failed job_id=%s", job_id)
        _mark_failed(job_id, "ZP_INTERNAL_ERROR")
    return get_job(job_id)


def get_conversion_job(job_id: str) -> ZpConversionJob | None:
    return get_job(job_id)


def cancel_conversion(job_id: str) -> ZpConversionJob | None:
    job = request_cancel(job_id)
    if job is None:
        return None
    if job.terminal:
        return job
    process_control.terminate_registered(job_id)
    _mark_cancelled(job)
    return get_job(job_id)


def list_dataset_assets(dataset_id: int) -> list[ZpArtifact]:
    return list_assets_for_dataset(dataset_id)


def latest_dataset_job(dataset_slug: str | None) -> ZpConversionJob | None:
    return latest_job_for_dataset_slug(dataset_slug)


def _worker_request(job: ZpConversionJob) -> WorkerRequest:
    if job.zp_temp_path is None or job.zp_final_path is None or job.validation_certificate_path is None:
        raise WorkerExecutionError("ZP_WORKER_INVALID_RESULT")
    return WorkerRequest(
        job_id=job.job_id,
        source_path=job.input_root,
        partial_path=job.zp_temp_path,
        final_path=job.zp_final_path,
        certificate_path=job.validation_certificate_path,
        temp_dir=job.zp_temp_path.parent,
        format_version=job.format_version,
        timeout_seconds=settings.zp_conversion_timeout_seconds,
        worker_threads=settings.zp_conversion_worker_threads,
        converter_path=settings.resolved_zp_thermo_converter(),
        binary_layer_commit=settings.zp_binary_layer_commit,
        v3_array_compression=settings.zp_v3_array_compression,
    )


def _register_success_asset(job: ZpConversionJob | None) -> None:
    if job is None or job.zp_final_path is None or job.output_sha256 is None:
        return
    dataset_id = dataset_id_for_slug(job.dataset_slug)
    if dataset_id is None:
        return
    register_asset(
        dataset_id=dataset_id,
        zp_path=job.zp_final_path,
        format_version=job.format_version,
        output_sha256=job.output_sha256,
        capabilities={"spectra": True},
    )


def _mark_failed(job_id: str, code: str) -> None:
    current = get_job(job_id)
    if current is not None:
        cleanup_job_paths(
            temp_dir=(current.zp_temp_path.parent if current.zp_temp_path else None),
            partial_path=current.zp_temp_path,
        )
    update_job(job_id, status="failed", stage="failed", progress=0.0, error_code=code, error_message=code)


def _mark_cancelled(job: ZpConversionJob) -> None:
    cleanup_job_paths(temp_dir=(job.zp_temp_path.parent if job.zp_temp_path else None), partial_path=job.zp_temp_path)
    update_job(job.job_id, status="cancelled", stage="cancelled", progress=0.0, error_code="ZP_WORKER_CANCELLED")


def _clean_slug(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
