"""Validate upload type and enqueue the existing path-import job."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.dataset_ingest_root import resolve_ingest_root
from app.import_uploads.errors import UploadError
from app.import_uploads.models import ImportType
from app.schemas.imports import ImportEnqueueIn, ImportJobCreatedOut
from app.services import import_jobs
from app.services.import_planner import ImportLayoutError, plan_zip_ingest
from app.services.import_planner.types import DatasetShape, ImportPlan


def _type_matches(import_type: ImportType, plan: ImportPlan) -> bool:
    checks = {
        ImportType.RAW_ONLY: plan.shape == DatasetShape.MZML_ONLY and plan.contains_raw,
        ImportType.MZML_ONLY: plan.shape == DatasetShape.MZML_ONLY and not plan.contains_raw,
        ImportType.TOPPIC: plan.shape == DatasetShape.TOPPIC_HTML,
        ImportType.PRSM: plan.shape == DatasetShape.PRSM_BUNDLE,
        ImportType.DIA_NN: plan.shape == DatasetShape.DIANN_DIA,
    }
    return checks[import_type]


def dispatch_import(
    *,
    import_type: ImportType,
    source_path: Path,
    parameters: dict[str, Any],
) -> ImportJobCreatedOut:
    if any(str(key).casefold() == "source_path" for key in parameters):
        raise UploadError("UPLOAD_INVALID_PATH", "上传导入参数不得包含 source_path。", 400)

    controlled_source = str(source_path.resolve(strict=True))
    try:
        request = ImportEnqueueIn.model_validate({**parameters, "source_path": controlled_source})
    except ValidationError as exc:
        raise UploadError("UPLOAD_IMPORT_PARAMETERS_INVALID", "导入参数无效。", 422) from exc

    try:
        ingest_root = resolve_ingest_root(source_path)
        plan = plan_zip_ingest(ingest_root)
    except (ImportLayoutError, ValueError, OSError) as exc:
        raise UploadError("UPLOAD_IMPORT_TYPE_UNSUPPORTED", "上传内容不符合所选导入类型。", 400) from exc
    if not _type_matches(import_type, plan):
        raise UploadError("UPLOAD_IMPORT_TYPE_UNSUPPORTED", "上传内容与所选导入类型不一致。", 400)

    job = import_jobs.enqueue_path_import(
        source_path=request.source_path,
        slug=request.slug.strip(),
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
    )
    return ImportJobCreatedOut(job_id=job.job_id, status="queued")
