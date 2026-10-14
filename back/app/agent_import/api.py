"""REST boundary for controlled unknown-format Agent Cases."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.agent_import import DEFAULT_WORKSPACE_ID
from app.agent_import.admission import admit_unknown_source_path
from app.agent_import.authorization import guard_workspace_request
from app.agent_import.authorization import require_internal_operator
from app.agent_import.local_sessions import claim_resource, check_resource, owned_ids
from app.agent_import.maintenance import MaintenanceFeedback, submit_feedback, list_feedback
from app.agent_import.input_assets import retained_asset_catalog, retained_asset_path
from app.agent_import.import_recipes import SaveRecipe, save_recipe, list_recipes, recipe_out, get_recipe_tx
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse
from app.agent_import.upload_admission import case_from_upload
from app.import_uploads.errors import UploadError
from app.agent_import.case_service import ArtifactRecord, CaseRecord, CaseService, get_case_service
from app.agent_import.errors import AgentImportError
from app.agent_import.schemas import (
    AgentExecutionRecoveryIn,
    AgentArtifactOut,
    AgentAttemptOut,
    AgentCandidateReworkIn,
    AgentCaseCreatedOut,
    AgentCaseFromPathIn,
    AgentCaseFromUploadIn,
    AgentCaseOut,
    AgentMessageCreateIn,
    AgentMessageOut,
    AgentNotificationCountOut,
    AgentNotificationOut,
)
from app.agent_import.workflow import AgentImportWorkflow
from app.core.config import settings
from app.dataset_capabilities import validate_capability_report


router = APIRouter(tags=["agent-import"], dependencies=[Depends(guard_workspace_request)])
delivery_read_router = APIRouter(tags=["agent-delivery"], dependencies=[Depends(guard_workspace_request)])


class RecipeImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=1)


class RevisionRollbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(min_length=1, max_length=80)
    expected_base: str = Field(min_length=1, max_length=80)


@router.get("/agent-import-cases/{case_id}/revisions")
def get_case_revisions(case_id: str):
    from .maintenance_publication import list_revisions
    try:
        return list_revisions(_service(), case_id)
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.post("/agent-import-cases/{case_id}/revisions/rollback")
def rollback_case_revision(case_id: str, body: RevisionRollbackIn):
    from .maintenance_publication import rollback_revision
    try:
        return rollback_revision(_service(), case_id, body.revision_id, body.expected_base)
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/import-recipes")
def get_import_recipes():
    return list_recipes(_service())


@router.post("/agent-import-cases/{case_id}/import-recipe")
def save_case_import_recipe(case_id: str, body: SaveRecipe):
    try:
        return recipe_out(save_recipe(_service(), case_id, body))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.post("/import-recipes/{recipe_id}/from-path", response_model=AgentCaseCreatedOut, status_code=201)
def import_saved_recipe(recipe_id: str, body: RecipeImportIn, request: Request):
    if not settings.agent_import_enabled:
        raise HTTPException(403, detail={"code": "AGENT_IMPORT_DISABLED"})
    try:
        with _service().engine.connect() as db:
            recipe = get_recipe_tx(db, recipe_id, body.version)
        admission = admit_unknown_source_path(body.source_path, enforce_policy=True)
        if getattr(request.state, "viewer_subject", None) and not admission.source_root.is_relative_to(settings.resolved_data_root):
            raise HTTPException(403, detail={"code": "SOURCE_OUTSIDE_SESSION_SCOPE"})
        case = _service().create_case(source_ref=str(admission.source_root), dataset_fingerprint=admission.dataset_fingerprint,
            analysis_category=recipe["analysis_category"], source_profile=recipe["name"], format_details=None,
            owner_id="shared-workspace", import_recipe=recipe, delivery_policy=_browser_delivery_policy("manual", request))
        claim_resource(request, "case", case.case_id)
        return AgentCaseCreatedOut(case_id=case.case_id, status=case.status.value, version=case.version)
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-retention/dry-run", dependencies=[Depends(require_internal_operator)])
def retention_dry_run():
    from .asset_retention import dry_run
    return {"mode": "dry_run_only", "assets": dry_run(_service().engine), "historical_files_scanned": False}


@router.post("/agent-import-cases/{case_id}/maintenance")
def create_maintenance_feedback(case_id: str, body: MaintenanceFeedback):
    try:
        return submit_feedback(_service(), case_id, body)
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-import-cases/{case_id}/maintenance")
def get_maintenance_feedback(case_id: str):
    return list_feedback(_service(), case_id)


@router.post("/agent-import-cases/{case_id}/recover-execution", response_model=AgentCaseOut, dependencies=[Depends(require_internal_operator)])
def recover_agent_execution(case_id: str, body: AgentExecutionRecoveryIn):
    from app.agent_import.recovery import recover_execution
    try:
        return _case_out(recover_execution(_service(), case_id, expected_version=body.expected_version, new_code_identity=body.new_code_identity))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


def _service() -> CaseService:
    return get_case_service()


def _case_out(case: CaseRecord) -> AgentCaseOut:
    return AgentCaseOut(
        progress=case.progress_payload,
        case_id=case.case_id,
        workspace_id=case.workspace_id,
        status=case.status.value,
        source_mode=case.source_mode,
        source_ref=f"agent-case:{case.case_id}",
        dataset_fingerprint=case.dataset_fingerprint,
        analysis_category=case.analysis_category,
        source_profile=case.source_profile,
        format_details=case.format_details,
        interaction_mode=case.interaction_mode.value,
        autonomous_attempt_used=case.autonomous_attempt_used,
        guided_attempt_no=case.guided_attempt_no,
        context_revision=case.context_revision,
        version=case.version,
        stop_requested_at=case.stop_requested_at,
        candidate_zp_sha256=case.candidate_zp_sha256,
        verification=_verification_out(case),
        dataset_id=case.dataset_id,
        dataset_slug=case.dataset_slug,
        created_at=case.created_at,
        updated_at=case.updated_at,
        deadline_at=case.deadline_at,
        model_tokens_reserved=case.model_tokens_reserved,
        delivery_policy=case.delivery_policy,
        ever_published=case.ever_published,
        authorization_wait_reason=case.authorization_wait_reason,
    )


def _artifact_out(artifact: ArtifactRecord) -> AgentArtifactOut:
    return AgentArtifactOut(
        artifact_id=artifact.artifact_id,
        case_id=artifact.case_id,
        attempt_id=artifact.attempt_id,
        artifact_type=artifact.artifact_type,
        storage_ref=f"agent-artifact:{artifact.artifact_id}",
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        media_type=artifact.media_type,
        structured_payload=artifact.structured_payload,
        created_at=artifact.created_at,
    )


def _verification_out(case: CaseRecord) -> dict[str, Any] | None:
    if case.verification_payload is None:
        return None
    verification = dict(case.verification_payload)
    report = verification.get("dataset_capability_report")
    if report is None:
        return verification
    try:
        validated = validate_capability_report(
            report,
            expected_dataset_id=case.dataset_id if case.dataset_id is not None else None,
        )
    except ValueError as exc:
        verification.pop("dataset_capability_report", None)
        verification["dataset_capability_report_error"] = {
            "code": "INVALID_DATASET_CAPABILITY_REPORT",
            "message": str(exc),
        }
    else:
        verification["dataset_capability_report"] = validated.model_dump(mode="json")
    return verification


@router.post("/agent-import-cases/from-path", response_model=AgentCaseCreatedOut, status_code=201)
def create_agent_case_from_path(body: AgentCaseFromPathIn, request: Request) -> AgentCaseCreatedOut:
    if not settings.agent_import_enabled:
        raise HTTPException(
            status_code=403,
            detail={"code": "AGENT_IMPORT_DISABLED", "message": "Agent import is disabled."},
        )
    try:
        admission = admit_unknown_source_path(body.source_path, enforce_policy=True)
        if getattr(request.state, "viewer_subject", None) and not admission.source_root.is_relative_to(settings.resolved_data_root):
            raise HTTPException(403, detail={"code": "SOURCE_OUTSIDE_SESSION_SCOPE"})
        case = _service().create_case(
            source_ref=str(admission.source_root),
            dataset_fingerprint=admission.dataset_fingerprint,
            analysis_category=_analysis_category(body.data_type),
            source_profile=body.format_name.strip(),
            format_details=body.format_details.strip() if body.format_details else None,
            delivery_policy=_browser_delivery_policy(body.delivery_policy, request),
            owner_id="shared-workspace",
        )
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    claim_resource(request, "case", case.case_id)
    return AgentCaseCreatedOut(case_id=case.case_id, status=case.status.value, version=case.version)


@router.post("/agent-import-cases/from-upload", response_model=AgentCaseCreatedOut, status_code=201)
def create_agent_case_from_upload(body: AgentCaseFromUploadIn, request: Request) -> AgentCaseCreatedOut:
    check_resource(request, "upload", body.upload_id)
    try:
        case = case_from_upload(_service(), body.upload_id, data_type=_analysis_category(body.data_type),
                                format_name=body.format_name.strip(), format_details=body.format_details, delivery_policy=_browser_delivery_policy(body.delivery_policy, request),
                                owner_id="shared-workspace")
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    except UploadError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    claim_resource(request, "case", case.case_id)
    return AgentCaseCreatedOut(case_id=case.case_id, status=case.status.value, version=case.version)


def _browser_delivery_policy(requested, request):
    # Anonymous shared-workspace access cannot promote the server's publication policy.
    if requested == "auto_test" and not settings.agent_auto_delivery_enabled:
        raise HTTPException(403, detail={"code": "AUTO_DELIVERY_NOT_AUTHORIZED"})
    return "auto_test" if settings.agent_auto_delivery_enabled else "manual"


@router.get("/agent-import-cases/{case_id}/handover")
@delivery_read_router.get("/agent-import-cases/{case_id}/handover")
def get_agent_handover(case_id: str) -> Response:
    artifacts = [item for item in _service().list_artifacts(case_id) if item.artifact_type == "handover"]
    if not artifacts:
        raise HTTPException(404, detail="No verified handover exists for this Case")
    payload = artifacts[-1].structured_payload or {}
    return Response(str(payload["markdown"]), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="HANDOVER.md"'})


@router.get("/agent-import-cases/{case_id}/source-assets")
@delivery_read_router.get("/agent-import-cases/{case_id}/source-assets")
def list_retained_source_assets(case_id: str) -> list[dict[str, Any]]:
    try:
        return retained_asset_catalog(_service().get_case(case_id))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-import-cases/{case_id}/source-assets/{asset_id}")
@delivery_read_router.get("/agent-import-cases/{case_id}/source-assets/{asset_id}")
def read_retained_source_asset(case_id: str, asset_id: str) -> FileResponse:
    try:
        path = retained_asset_path(_service().get_case(case_id), asset_id)
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/agent-import-cases", response_model=list[AgentCaseOut])
def list_agent_cases(request: Request, workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID)) -> list[AgentCaseOut]:
    allowed = owned_ids(request, "case")
    return [_case_out(case) for case in _service().list_cases(workspace_id=workspace_id) if allowed is None or case.case_id in allowed]


@router.get("/agent-import-cases/{case_id}", response_model=AgentCaseOut)
def get_agent_case(case_id: str) -> AgentCaseOut:
    try:
        return _case_out(_service().get_case(case_id))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-import-cases/{case_id}/messages", response_model=list[AgentMessageOut])
def list_agent_messages(case_id: str) -> list[AgentMessageOut]:
    try:
        return [AgentMessageOut(**asdict(message)) for message in _service().list_messages(case_id)]
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-import-cases/{case_id}/attempts", response_model=list[AgentAttemptOut])
def list_agent_attempts(case_id: str) -> list[AgentAttemptOut]:
    try:
        return [AgentAttemptOut(**asdict(attempt)) for attempt in _service().list_attempts(case_id)]
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-import-cases/{case_id}/artifacts", response_model=list[AgentArtifactOut])
def list_agent_artifacts(case_id: str) -> list[AgentArtifactOut]:
    try:
        return [_artifact_out(artifact) for artifact in _service().list_artifacts(case_id)]
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.post("/agent-import-cases/{case_id}/messages", response_model=AgentCaseOut)
def post_agent_message(
    case_id: str,
    body: AgentMessageCreateIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AgentCaseOut:
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "AGENT_IDEMPOTENCY_REQUIRED", "message": "Idempotency-Key is required."},
        )
    try:
        case = _service().submit_user_answer(
            case_id,
            content=body.content,
            expected_version=_expected_version(if_match),
            idempotency_key=idempotency_key,
        )
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    return _case_out(case)


@router.post("/agent-import-cases/{case_id}/review/approve", response_model=AgentCaseOut)
def approve_agent_case(
    case_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> AgentCaseOut:
    try:
        case = AgentImportWorkflow(service=_service()).approve_case(
            case_id,
            expected_version=_expected_version(if_match),
        )
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    return _case_out(case)


@router.post("/agent-import-cases/{case_id}/review/rework", response_model=AgentCaseOut)
def rework_agent_case(
    case_id: str,
    body: AgentCandidateReworkIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> AgentCaseOut:
    try:
        case = _service().request_rework(
            case_id,
            feedback=body.feedback,
            expected_version=_expected_version(if_match),
        )
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    return _case_out(case)


@router.post("/agent-import-cases/{case_id}/stop", response_model=AgentCaseOut)
def stop_agent_case(case_id: str) -> AgentCaseOut:
    try:
        return _case_out(_service().request_stop(case_id))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.post("/agent-import-cases/{case_id}/retry", response_model=AgentCaseOut)
def retry_agent_case(case_id: str, if_match: str | None = Header(default=None, alias="If-Match")):
    from .task_retry import retry_task
    try:
        return _case_out(retry_task(_service(), case_id, _expected_version(if_match)))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.post("/agent-import-cases/{case_id}/reverify", response_model=AgentCaseOut)
def reverify_agent_case(case_id: str, if_match: str | None = Header(default=None, alias="If-Match")):
    from .task_retry import reverify_candidate
    try:
        return _case_out(reverify_candidate(_service(), case_id, _expected_version(if_match)))
    except AgentImportError as exc:
        raise _http_error(exc) from exc


@router.get("/agent-notifications", response_model=list[AgentNotificationOut])
def list_agent_notifications(
    request: Request,
    workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID),
) -> list[AgentNotificationOut]:
    allowed = owned_ids(request, "case")
    return [AgentNotificationOut(**asdict(item)) for item in _service().list_notifications(workspace_id=workspace_id) if allowed is None or item.case_id in allowed]


@router.get("/agent-notifications/count", response_model=AgentNotificationCountOut)
def count_agent_notifications(request: Request, workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID)) -> AgentNotificationCountOut:
    return AgentNotificationCountOut(count=len(list_agent_notifications(request, workspace_id)))


def _analysis_category(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise AgentImportError(
            "AGENT_ANALYSIS_CATEGORY_INVALID",
            "data_type must contain an analysis category.",
            status_code=422,
        )
    normalized = re_normalize(value)
    mapping = {
        "topdown": "TOP_DOWN",
        "bottomup": "BOTTOM_UP",
        "spectraonly": "SPECTRA_ONLY",
        "spectrumonly": "SPECTRA_ONLY",
    }
    return mapping.get(normalized, cleaned)


def re_normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _expected_version(value: str | None) -> int:
    if not value:
        raise HTTPException(
            status_code=428,
            detail={"code": "AGENT_IF_MATCH_REQUIRED", "message": "If-Match is required."},
        )
    try:
        return int(value.strip().strip('"'))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "AGENT_IF_MATCH_INVALID", "message": "If-Match must contain the Case version."},
        ) from exc


def _http_error(exc: AgentImportError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
