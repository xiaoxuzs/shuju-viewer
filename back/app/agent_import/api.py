"""REST boundary for controlled unknown-format Agent Cases."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, Query

from app.agent_import import DEFAULT_WORKSPACE_ID
from app.agent_import.admission import admit_unknown_source_path
from app.agent_import.case_service import ArtifactRecord, CaseRecord, CaseService, get_case_service
from app.agent_import.errors import AgentImportError
from app.agent_import.schemas import (
    AgentArtifactOut,
    AgentAttemptOut,
    AgentCandidateReworkIn,
    AgentCaseCreatedOut,
    AgentCaseFromPathIn,
    AgentCaseOut,
    AgentMessageCreateIn,
    AgentMessageOut,
    AgentNotificationCountOut,
    AgentNotificationOut,
)
from app.agent_import.workflow import AgentImportWorkflow
from app.core.config import settings


router = APIRouter(tags=["agent-import"])


def _service() -> CaseService:
    return get_case_service()


def _case_out(case: CaseRecord) -> AgentCaseOut:
    return AgentCaseOut(
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
        verification=case.verification_payload,
        dataset_id=case.dataset_id,
        dataset_slug=case.dataset_slug,
        created_at=case.created_at,
        updated_at=case.updated_at,
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
        created_at=artifact.created_at,
    )


@router.post("/agent-import-cases/from-path", response_model=AgentCaseCreatedOut, status_code=201)
def create_agent_case_from_path(body: AgentCaseFromPathIn) -> AgentCaseCreatedOut:
    if not settings.agent_import_enabled:
        raise HTTPException(
            status_code=403,
            detail={"code": "AGENT_IMPORT_DISABLED", "message": "Agent import is disabled."},
        )
    try:
        admission = admit_unknown_source_path(body.source_path)
        case = _service().create_case(
            source_ref=str(admission.source_root),
            dataset_fingerprint=admission.dataset_fingerprint,
            analysis_category=_analysis_category(body.data_type),
            source_profile=body.format_name.strip(),
            format_details=body.format_details.strip() if body.format_details else None,
        )
    except AgentImportError as exc:
        raise _http_error(exc) from exc
    return AgentCaseCreatedOut(case_id=case.case_id, status=case.status.value, version=case.version)


@router.get("/agent-import-cases", response_model=list[AgentCaseOut])
def list_agent_cases(workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID)) -> list[AgentCaseOut]:
    return [_case_out(case) for case in _service().list_cases(workspace_id=workspace_id)]


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


@router.get("/agent-notifications", response_model=list[AgentNotificationOut])
def list_agent_notifications(
    workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID),
) -> list[AgentNotificationOut]:
    return [AgentNotificationOut(**asdict(item)) for item in _service().list_notifications(workspace_id=workspace_id)]


@router.get("/agent-notifications/count", response_model=AgentNotificationCountOut)
def count_agent_notifications(workspace_id: str = Query(default=DEFAULT_WORKSPACE_ID)) -> AgentNotificationCountOut:
    return AgentNotificationCountOut(count=len(_service().list_notifications(workspace_id=workspace_id)))


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
