"""Validate an explicit upload type and enqueue the shared path-import job."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.dataset_ingest_root import resolve_ingest_root
from app.import_types import ImportType
from app.import_uploads.errors import UploadError
from app.schemas.imports import ImportEnqueueIn, ImportJobCreatedOut
from app.services import import_jobs
from app.services.import_planner import ImportLayoutError, plan_zip_ingest
from app.services.import_selection import ImportSelectionError, validate_import_selection


def dispatch_import(
    *,
    import_type: ImportType,
    source_path: Path,
    parameters: dict[str, Any],
) -> ImportJobCreatedOut:
    if any(str(key).casefold() == "source_path" for key in parameters):
        raise UploadError("UPLOAD_INVALID_PATH", "Upload import parameters must not contain source_path.", 400)
    if any(str(key).casefold() == "import_type" for key in parameters):
        raise UploadError(
            "UPLOAD_IMPORT_PARAMETERS_INVALID",
            "Upload import parameters must not override the type selected for the upload session.",
            400,
        )

    controlled_source = str(source_path.resolve(strict=True))
    try:
        request = ImportEnqueueIn.model_validate({**parameters, "source_path": controlled_source})
    except ValidationError as exc:
        raise UploadError("UPLOAD_IMPORT_PARAMETERS_INVALID", "Import parameters are invalid.", 422) from exc

    try:
        ingest_root = resolve_ingest_root(source_path)
        plan = plan_zip_ingest(ingest_root)
        validate_import_selection(import_type, ingest_root, plan)
    except (ImportLayoutError, ImportSelectionError, ValueError, OSError) as exc:
        raise UploadError(
            "UPLOAD_IMPORT_TYPE_UNSUPPORTED",
            f"Uploaded content does not satisfy the selected {import_type.value} import contract: {exc}",
            400,
        ) from exc

    job = import_jobs.enqueue_path_import(
        source_path=request.source_path,
        slug=request.slug.strip(),
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        import_type=import_type.value,
    )
    return ImportJobCreatedOut(job_id=job.job_id, status="queued")
