"""Idempotently pin an existing complete managed upload before queuing its Case."""

from datetime import datetime, timezone
import uuid

from app.agent_import.admission import admit_unknown_source_path
from app.agent_import.case_service import CaseService
from app.agent_import.errors import AgentImportError
from app.import_types import ImportType
from app.import_uploads.errors import UploadError
from app.import_uploads.locking import upload_lock
from app.import_uploads.manifest import manifest_path, read_manifest, write_manifest
from app.import_uploads.models import UploadState
from app.import_uploads.paths import require_enabled


def case_from_upload(service: CaseService, upload_id: str, *, data_type: str, format_name: str, format_details: str | None, delivery_policy: str = "manual", owner_id: str = "unowned"):
    from app.import_uploads.service import _validate_ready_files
    require_enabled()
    if delivery_policy == "auto_test":
        from app.agent_import.delivery import require_auto_test_policy
        require_auto_test_policy()
    with upload_lock(upload_id):
        manifest = read_manifest(upload_id)
        if manifest.import_type != ImportType.AGENT_UNKNOWN:
            raise UploadError("UPLOAD_INVALID_STATE", "Use an Agent upload session for unknown formats", 409)
        if manifest.job_id or manifest.state not in {UploadState.READY, UploadState.CASE_PINNED}:
            raise UploadError("UPLOAD_INVALID_STATE", "The upload is incomplete or already dispatched", 409)
        root = _validate_ready_files(upload_id, manifest)
        admission = admit_unknown_source_path(root, enforce_policy=True)
        case_id = manifest.case_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"viewer-managed-upload:{upload_id}"))
        # Pin first. A DB outage leaves a safe, retryable pin rather than an
        # unprotected source. The deterministic Case PK is the DB uniqueness key.
        manifest.state = UploadState.CASE_PINNED
        manifest.case_id = case_id
        manifest.started_at = manifest.started_at or datetime.now(timezone.utc)
        write_manifest(manifest_path(upload_id), manifest)
        try:
            existing = service.get_case(case_id)
        except AgentImportError as exc:
            if exc.code != "AGENT_CASE_NOT_FOUND":
                raise
        else:
            if (existing.analysis_category, existing.source_profile, existing.format_details, existing.delivery_policy, existing.owner_id) != (
                data_type, format_name, format_details, delivery_policy, owner_id,
            ):
                raise AgentImportError("AGENT_UPLOAD_CONFLICT", "This upload already belongs to a different Case request.", status_code=409)
            if existing.dataset_fingerprint != admission.dataset_fingerprint:
                from .input_assets import content_manifest
                if not existing.source_content_sha256 or existing.source_content_sha256 != content_manifest(root)["sha256"]:
                    raise AgentImportError("AGENT_UPLOAD_CONFLICT", "Pinned source content changed", status_code=409)
            return existing
        created = service.create_case(case_id=case_id, source_ref=str(root), dataset_fingerprint=admission.dataset_fingerprint,
                                   analysis_category=data_type, source_profile=format_name, format_details=format_details,
                                   source_mode="MANAGED_UPLOAD", delivery_policy=delivery_policy, owner_id=owner_id)
        if created.case_id != manifest.case_id:
            manifest.case_id = created.case_id
            write_manifest(manifest_path(upload_id), manifest)
        return created
