"""HTTP schemas for the Agent Import Case API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentCaseFromPathIn(BaseModel):
    source_path: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1, max_length=80)
    format_name: str = Field(..., min_length=1, max_length=160)
    format_details: str | None = Field(default=None, max_length=4000)


class AgentCaseCreatedOut(BaseModel):
    case_id: str
    status: str
    version: int


class AgentCaseOut(BaseModel):
    case_id: str
    workspace_id: str
    status: str
    source_mode: str
    source_ref: str
    dataset_fingerprint: str
    analysis_category: str
    source_profile: str
    format_details: str | None
    interaction_mode: str
    autonomous_attempt_used: int
    guided_attempt_no: int
    context_revision: int
    version: int
    stop_requested_at: str | None
    candidate_zp_sha256: str | None
    verification: dict[str, Any] | None
    dataset_id: int | None
    dataset_slug: str | None
    created_at: str
    updated_at: str


class AgentMessageOut(BaseModel):
    message_id: str
    case_id: str
    sequence_no: int
    context_revision: int
    sender_type: str
    message_kind: str
    content: str
    structured_payload: dict[str, Any] | None
    created_at: str


class AgentAttemptOut(BaseModel):
    attempt_id: str
    case_id: str
    attempt_no: int
    context_revision: int
    result: str
    failure_code: str | None
    started_at: str
    finished_at: str


class AgentArtifactOut(BaseModel):
    artifact_id: str
    case_id: str
    attempt_id: str | None
    artifact_type: str
    storage_ref: str
    sha256: str
    size_bytes: int
    media_type: str | None
    created_at: str


class AgentMessageCreateIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class AgentCandidateReworkIn(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=4000)


class AgentNotificationOut(BaseModel):
    notification_id: str
    case_id: str
    kind: str
    title: str
    summary: str
    created_at: str


class AgentNotificationCountOut(BaseModel):
    count: int
