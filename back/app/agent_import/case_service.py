"""Persistent Agent Case state, audit messages, attempts, and artifacts."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.agent_import import AUTONOMOUS_ATTEMPT_LIMIT, DEFAULT_WORKSPACE_ID
from app.agent_import.binary_executor import BinaryExecutionResult
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentImportError
from app.agent_import.states import CaseStatus, InteractionMode, TERMINAL_STATUSES, assert_transition
from app.core.db import engine as default_engine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if value is not None else None


def _object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class CaseRecord:
    case_id: str
    workspace_id: str
    status: CaseStatus
    source_mode: str
    source_ref: str
    dataset_fingerprint: str
    analysis_category: str
    source_profile: str
    format_details: str | None
    interaction_mode: InteractionMode
    autonomous_attempt_used: int
    guided_attempt_no: int
    context_revision: int
    version: int
    lease_owner: str | None
    lease_expires_at: str | None
    stop_requested_at: str | None
    strategy_payload: dict[str, Any] | None
    candidate_payload: dict[str, Any] | None
    verification_payload: dict[str, Any] | None
    candidate_zp_path: str | None
    candidate_zp_sha256: str | None
    dataset_id: int | None
    dataset_slug: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MessageRecord:
    message_id: str
    case_id: str
    sequence_no: int
    context_revision: int
    sender_type: str
    message_kind: str
    content: str
    structured_payload: dict[str, Any] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    case_id: str
    attempt_no: int
    context_revision: int
    result: str
    failure_code: str | None
    started_at: str
    finished_at: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    case_id: str
    attempt_id: str | None
    artifact_type: str
    storage_ref: str
    sha256: str
    size_bytes: int
    media_type: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    notification_id: str
    case_id: str
    kind: str
    title: str
    summary: str
    created_at: str


def _case(row: Any) -> CaseRecord:
    return CaseRecord(
        case_id=str(row["case_id"]),
        workspace_id=str(row["workspace_id"]),
        status=CaseStatus(str(row["status"])),
        source_mode=str(row["source_mode"]),
        source_ref=str(row["source_ref"]),
        dataset_fingerprint=str(row["dataset_fingerprint"]),
        analysis_category=str(row["analysis_category"]),
        source_profile=str(row["source_profile"]),
        format_details=row["format_details"],
        interaction_mode=InteractionMode(str(row["interaction_mode"])),
        autonomous_attempt_used=int(row["autonomous_attempt_used"]),
        guided_attempt_no=int(row["guided_attempt_no"]),
        context_revision=int(row["context_revision"]),
        version=int(row["version"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        stop_requested_at=row["stop_requested_at"],
        strategy_payload=_object(row["strategy_payload"]),
        candidate_payload=_object(row["candidate_payload"]),
        verification_payload=_object(row["verification_payload"]),
        candidate_zp_path=row["candidate_zp_path"],
        candidate_zp_sha256=row["candidate_zp_sha256"],
        dataset_id=int(row["dataset_id"]) if row["dataset_id"] is not None else None,
        dataset_slug=row["dataset_slug"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class CaseService:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def create_case(
        self,
        *,
        source_ref: str,
        dataset_fingerprint: str,
        analysis_category: str,
        source_profile: str,
        format_details: str | None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        source_mode: str = "LOCAL_PATH",
    ) -> CaseRecord:
        case_id = str(uuid.uuid4())
        now = _now()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO agent_import_cases (
                        case_id, workspace_id, status, source_mode, source_ref,
                        dataset_fingerprint, analysis_category, source_profile, format_details,
                        interaction_mode, created_at, updated_at
                    ) VALUES (
                        :case_id, :workspace_id, :status, :source_mode, :source_ref,
                        :fingerprint, :category, :profile, :details,
                        :interaction_mode, :now, :now
                    )
                    """
                ),
                {
                    "case_id": case_id,
                    "workspace_id": workspace_id,
                    "status": CaseStatus.CREATED.value,
                    "source_mode": source_mode,
                    "source_ref": source_ref,
                    "fingerprint": dataset_fingerprint,
                    "category": analysis_category,
                    "profile": source_profile,
                    "details": format_details,
                    "interaction_mode": InteractionMode.AUTONOMOUS.value,
                    "now": now,
                },
            )
            self._append_message(
                connection,
                case_id=case_id,
                context_revision=1,
                sender_type="SYSTEM",
                message_kind="STATUS",
                content="Agent Case created and queued for source analysis.",
                payload={"event": "case_created"},
                created_at=now,
            )
        return self.get_case(case_id)

    def get_case(self, case_id: str) -> CaseRecord:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM agent_import_cases WHERE case_id = :case_id"),
                {"case_id": case_id},
            ).mappings().first()
        if row is None:
            raise AgentImportError("AGENT_CASE_NOT_FOUND", "Agent Case not found.", status_code=404)
        return _case(row)

    def list_cases(self, *, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[CaseRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT * FROM agent_import_cases
                    WHERE workspace_id = :workspace_id
                    ORDER BY updated_at DESC
                    """
                ),
                {"workspace_id": workspace_id},
            ).mappings().all()
        return [_case(row) for row in rows]

    def list_messages(self, case_id: str) -> list[MessageRecord]:
        self.get_case(case_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM agent_messages WHERE case_id = :case_id ORDER BY sequence_no"),
                {"case_id": case_id},
            ).mappings().all()
        return [
            MessageRecord(
                message_id=str(row["message_id"]),
                case_id=str(row["case_id"]),
                sequence_no=int(row["sequence_no"]),
                context_revision=int(row["context_revision"]),
                sender_type=str(row["sender_type"]),
                message_kind=str(row["message_kind"]),
                content=str(row["content"]),
                structured_payload=_object(row["structured_payload"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def list_attempts(self, case_id: str) -> list[AttemptRecord]:
        self.get_case(case_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM agent_attempts WHERE case_id = :case_id ORDER BY started_at"),
                {"case_id": case_id},
            ).mappings().all()
        return [
            AttemptRecord(
                attempt_id=str(row["attempt_id"]),
                case_id=str(row["case_id"]),
                attempt_no=int(row["attempt_no"]),
                context_revision=int(row["context_revision"]),
                result=str(row["result"]),
                failure_code=row["failure_code"],
                started_at=str(row["started_at"]),
                finished_at=str(row["finished_at"]),
            )
            for row in rows
        ]

    def list_artifacts(self, case_id: str) -> list[ArtifactRecord]:
        self.get_case(case_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM agent_artifacts WHERE case_id = :case_id ORDER BY created_at"),
                {"case_id": case_id},
            ).mappings().all()
        return [
            ArtifactRecord(
                artifact_id=str(row["artifact_id"]),
                case_id=str(row["case_id"]),
                attempt_id=str(row["attempt_id"]) if row["attempt_id"] else None,
                artifact_type=str(row["artifact_type"]),
                storage_ref=str(row["storage_ref"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
                media_type=row["media_type"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def claim_next(self, *, worker_id: str, lease_seconds: int = 9_000) -> CaseRecord | None:
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self.engine.begin() as connection:
            lock = " FOR UPDATE SKIP LOCKED" if connection.dialect.name != "sqlite" else ""
            row = connection.execute(
                text(
                    """
                    SELECT * FROM agent_import_cases
                    WHERE status IN ('CREATED', 'ANALYZING', 'STOPPING')
                      AND (lease_owner IS NULL OR lease_expires_at < :now)
                    ORDER BY created_at
                    LIMIT 1
                    """ + lock
                ),
                {"now": now},
            ).mappings().first()
            if row is None:
                return None
            connection.execute(
                text(
                    """
                    UPDATE agent_import_cases
                    SET lease_owner = :worker_id, lease_expires_at = :expires,
                        version = version + 1, updated_at = :now
                    WHERE case_id = :case_id
                    """
                ),
                {"worker_id": worker_id, "expires": expires, "now": now, "case_id": row["case_id"]},
            )
        return self.get_case(str(row["case_id"]))

    def start_analysis(self, case_id: str) -> CaseRecord:
        case = self.get_case(case_id)
        if case.status == CaseStatus.ANALYZING:
            return case
        return self._transition(
            case,
            CaseStatus.ANALYZING,
            content="Agent 1 is analyzing the bounded source summary.",
            payload={"event": "analyzing"},
            sender_type="AGENT_1",
            release_lease=False,
        )

    def save_strategy(self, case_id: str, payload: dict[str, Any]) -> CaseRecord:
        case = self.get_case(case_id)
        updated = self._transition(
            case,
            CaseStatus.STRATEGY_READY,
            content="Agent 1 produced a structured source strategy.",
            payload={"event": "strategy_ready", "strategy": payload},
            sender_type="AGENT_1",
            updates={"strategy_payload": _json(payload)},
            release_lease=False,
        )
        self._record_json_artifact(updated.case_id, "strategy", payload)
        return updated

    def save_candidate(self, case_id: str, plan: AgentCandidatePlan) -> CaseRecord:
        payload = plan.model_dump(mode="json")
        case = self.get_case(case_id)
        updated = self._transition(
            case,
            CaseStatus.BUILDING,
            content="Agent 2 produced a whitelisted ZP conversion plan.",
            payload={"event": "candidate_ready", "candidate": payload},
            sender_type="AGENT_2",
            updates={"candidate_payload": _json(payload)},
            release_lease=False,
        )
        self._record_json_artifact(updated.case_id, "candidate_plan", payload)
        return updated

    def start_verification(self, case_id: str) -> CaseRecord:
        return self._transition(
            self.get_case(case_id),
            CaseStatus.VERIFYING,
            content="The deterministic verifier is executing the approved ZP operation.",
            payload={"event": "verifying"},
            sender_type="SYSTEM",
            release_lease=False,
        )

    def record_ready(self, case_id: str, result: BinaryExecutionResult) -> CaseRecord:
        case = self.get_case(case_id)
        verification = {
            "binary_operation": (case.candidate_payload or {}).get("binary_operation"),
            "zp_output_sha256": result.output_sha256,
            "zp_format_version": result.format_version,
            "source_fingerprint": result.source_fingerprint,
            "validation_mode": result.validation_mode,
            "deep_validation_certificate": bool(result.validation_certificate_path),
        }
        now = _now()
        with self.engine.begin() as connection:
            current = self._locked_case(connection, case_id)
            assert_transition(current.status, CaseStatus.READY_FOR_REVIEW)
            attempt_id, attempt_no = self._insert_attempt(connection, current, "PASSED", None, now)
            self._insert_file_artifact(connection, current, attempt_id, "candidate_zp", result.zp_path, now)
            if result.validation_certificate_path and result.validation_certificate_path.is_file():
                self._insert_file_artifact(
                    connection,
                    current,
                    attempt_id,
                    "deep_validation_certificate",
                    result.validation_certificate_path,
                    now,
                )
            self._insert_json_artifact_tx(connection, current, attempt_id, "verification_summary", verification, now)
            connection.execute(
                text(
                    """
                    UPDATE agent_import_cases
                    SET status = :status, verification_payload = :verification,
                        candidate_zp_path = :zp_path, candidate_zp_sha256 = :sha256,
                        lease_owner = NULL, lease_expires_at = NULL,
                        version = version + 1, updated_at = :now
                    WHERE case_id = :case_id
                    """
                ),
                {
                    "status": CaseStatus.READY_FOR_REVIEW.value,
                    "verification": _json(verification),
                    "zp_path": str(result.zp_path),
                    "sha256": result.output_sha256,
                    "now": now,
                    "case_id": case_id,
                },
            )
            self._append_message(
                connection,
                case_id=case_id,
                context_revision=current.context_revision,
                sender_type="SYSTEM",
                message_kind="EVIDENCE",
                content=f"ZP candidate passed deep validation in attempt {attempt_no} and is ready for review.",
                payload={"event": "ready_for_review", "verification": verification},
                created_at=now,
            )
        return self.get_case(case_id)

    def record_failure(self, case_id: str, *, code: str, summary: str) -> CaseRecord:
        now = _now()
        with self.engine.begin() as connection:
            current = self._locked_case(connection, case_id)
            if current.status == CaseStatus.STOPPING:
                target = CaseStatus.STOPPED
                used = current.autonomous_attempt_used
            elif current.interaction_mode == InteractionMode.AUTONOMOUS:
                used = current.autonomous_attempt_used + 1
                target = CaseStatus.ANALYZING if used < AUTONOMOUS_ATTEMPT_LIMIT else CaseStatus.NEEDS_USER
            else:
                used = current.autonomous_attempt_used
                target = CaseStatus.NEEDS_USER
            assert_transition(current.status, target)
            self._insert_attempt(connection, current, "FAILED", code, now)
            connection.execute(
                text(
                    """
                    UPDATE agent_import_cases
                    SET status = :status, autonomous_attempt_used = :used,
                        verification_payload = :verification,
                        lease_owner = NULL, lease_expires_at = NULL,
                        version = version + 1, updated_at = :now
                    WHERE case_id = :case_id
                    """
                ),
                {
                    "status": target.value,
                    "used": used,
                    "verification": _json({"passed": False, "failure_code": code, "summary": summary}),
                    "now": now,
                    "case_id": case_id,
                },
            )
            self._append_message(
                connection,
                case_id=case_id,
                context_revision=current.context_revision,
                sender_type="SYSTEM",
                message_kind="QUESTION" if target == CaseStatus.NEEDS_USER else "EVIDENCE",
                content=summary,
                payload={"event": "verification_failed", "failure_code": code, "next_status": target.value},
                created_at=now,
            )
            if target == CaseStatus.NEEDS_USER:
                self._create_notification(connection, current, summary, now)
        return self.get_case(case_id)

    def submit_user_answer(
        self,
        case_id: str,
        *,
        content: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CaseRecord:
        answer = content.strip()
        if not answer:
            raise AgentImportError("AGENT_ANSWER_REQUIRED", "Answer is required.", status_code=422)
        now = _now()
        with self.engine.begin() as connection:
            current = self._locked_case(connection, case_id)
            existing = connection.execute(
                text(
                    "SELECT message_id FROM agent_messages WHERE case_id = :case_id AND idempotency_key = :key"
                ),
                {"case_id": case_id, "key": idempotency_key},
            ).first()
            if existing is not None:
                return current
            self._require_version(current, expected_version)
            if current.status != CaseStatus.NEEDS_USER:
                raise AgentImportError(
                    "AGENT_CASE_STATE_CONFLICT",
                    "Case is not waiting for an answer.",
                    status_code=409,
                )
            assert_transition(current.status, CaseStatus.ANALYZING)
            revision = current.context_revision + 1
            connection.execute(
                text(
                    """
                    UPDATE agent_import_cases
                    SET status = :status, interaction_mode = :mode,
                        guided_attempt_no = guided_attempt_no + 1,
                        context_revision = :revision, lease_owner = NULL, lease_expires_at = NULL,
                        version = version + 1, updated_at = :now
                    WHERE case_id = :case_id
                    """
                ),
                {
                    "status": CaseStatus.ANALYZING.value,
                    "mode": InteractionMode.GUIDED.value,
                    "revision": revision,
                    "now": now,
                    "case_id": case_id,
                },
            )
            self._append_message(
                connection,
                case_id=case_id,
                context_revision=revision,
                sender_type="USER",
                message_kind="TEXT",
                content=answer,
                payload={"event": "user_answer"},
                created_at=now,
                idempotency_key=idempotency_key,
            )
            self._resolve_notifications(connection, case_id, now)
        return self.get_case(case_id)

    def request_rework(self, case_id: str, *, feedback: str, expected_version: int) -> CaseRecord:
        note = feedback.strip()
        if not note:
            raise AgentImportError("AGENT_REWORK_REQUIRED", "Rework feedback is required.", status_code=422)
        current = self.get_case(case_id)
        self._require_version(current, expected_version)
        if current.status != CaseStatus.READY_FOR_REVIEW:
            raise AgentImportError("AGENT_CASE_STATE_CONFLICT", "Case is not ready for review.", status_code=409)
        revision = current.context_revision + 1
        return self._transition(
            current,
            CaseStatus.ANALYZING,
            content=note,
            payload={"event": "rework_requested"},
            sender_type="USER",
            updates={
                "interaction_mode": InteractionMode.GUIDED.value,
                "guided_attempt_no": current.guided_attempt_no + 1,
                "context_revision": revision,
                "candidate_zp_path": None,
                "candidate_zp_sha256": None,
            },
            release_lease=True,
            message_context_revision=revision,
        )

    def mark_success(self, case_id: str, *, dataset_id: int, dataset_slug: str) -> CaseRecord:
        return self._transition(
            self.get_case(case_id),
            CaseStatus.SUCCESS,
            content="Approved ZP candidate was imported and verified by Viewer.",
            payload={"event": "import_success", "dataset_id": dataset_id, "dataset_slug": dataset_slug},
            sender_type="SYSTEM",
            updates={"dataset_id": dataset_id, "dataset_slug": dataset_slug},
            release_lease=True,
        )

    def request_stop(self, case_id: str) -> CaseRecord:
        current = self.get_case(case_id)
        if current.status in TERMINAL_STATUSES:
            return current
        target = (
            CaseStatus.STOPPED
            if current.status in {CaseStatus.CREATED, CaseStatus.NEEDS_USER, CaseStatus.READY_FOR_REVIEW}
            else CaseStatus.STOPPING
        )
        return self._transition(
            current,
            target,
            content="Agent Case stop requested.",
            payload={"event": "stop_requested"},
            sender_type="SYSTEM",
            updates={"stop_requested_at": _now()},
            release_lease=target == CaseStatus.STOPPED,
        )

    def finish_stopping(self, case_id: str) -> CaseRecord:
        current = self.get_case(case_id)
        if current.status != CaseStatus.STOPPING:
            return current
        return self._transition(
            current,
            CaseStatus.STOPPED,
            content="Agent Case stopped.",
            payload={"event": "stopped"},
            sender_type="SYSTEM",
            release_lease=True,
        )

    def list_notifications(self, *, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[NotificationRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT n.* FROM agent_notifications n
                    JOIN agent_import_cases c ON c.case_id = n.case_id
                    WHERE c.workspace_id = :workspace_id AND n.active = 1
                    ORDER BY n.created_at DESC
                    """
                ),
                {"workspace_id": workspace_id},
            ).mappings().all()
        return [
            NotificationRecord(
                notification_id=str(row["notification_id"]),
                case_id=str(row["case_id"]),
                kind=str(row["kind"]),
                title=str(row["title"]),
                summary=str(row["summary"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def _transition(
        self,
        current: CaseRecord,
        target: CaseStatus,
        *,
        content: str,
        payload: dict[str, Any],
        sender_type: str,
        updates: dict[str, Any] | None = None,
        release_lease: bool,
        message_context_revision: int | None = None,
    ) -> CaseRecord:
        assert_transition(current.status, target)
        now = _now()
        fields = {"status": target.value, "updated_at": now, **(updates or {})}
        if release_lease:
            fields.update(lease_owner=None, lease_expires_at=None)
        allowed = {
            "status",
            "updated_at",
            "strategy_payload",
            "candidate_payload",
            "verification_payload",
            "candidate_zp_path",
            "candidate_zp_sha256",
            "interaction_mode",
            "guided_attempt_no",
            "context_revision",
            "dataset_id",
            "dataset_slug",
            "stop_requested_at",
            "lease_owner",
            "lease_expires_at",
        }
        if not set(fields).issubset(allowed):
            raise ValueError("unsupported Agent Case update field")
        assignments = ", ".join(f"{name} = :{name}" for name in fields)
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    f"""
                    UPDATE agent_import_cases
                    SET {assignments}, version = version + 1
                    WHERE case_id = :case_id AND status = :expected_status
                    """
                ),
                {**fields, "case_id": current.case_id, "expected_status": current.status.value},
            )
            if result.rowcount != 1:
                raise AgentImportError(
                    "AGENT_CASE_VERSION_CONFLICT",
                    "Agent Case changed concurrently.",
                    status_code=409,
                )
            self._append_message(
                connection,
                case_id=current.case_id,
                context_revision=message_context_revision or current.context_revision,
                sender_type=sender_type,
                message_kind="STATUS",
                content=content,
                payload=payload,
                created_at=now,
            )
        return self.get_case(current.case_id)

    def _locked_case(self, connection: Any, case_id: str) -> CaseRecord:
        lock = " FOR UPDATE" if connection.dialect.name != "sqlite" else ""
        row = connection.execute(
            text("SELECT * FROM agent_import_cases WHERE case_id = :case_id" + lock),
            {"case_id": case_id},
        ).mappings().first()
        if row is None:
            raise AgentImportError("AGENT_CASE_NOT_FOUND", "Agent Case not found.", status_code=404)
        return _case(row)

    def _append_message(
        self,
        connection: Any,
        *,
        case_id: str,
        context_revision: int,
        sender_type: str,
        message_kind: str,
        content: str,
        payload: dict[str, Any] | None,
        created_at: str,
        idempotency_key: str | None = None,
    ) -> None:
        sequence = int(
            connection.execute(
                text("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_messages WHERE case_id = :case_id"),
                {"case_id": case_id},
            ).scalar_one()
        )
        connection.execute(
            text(
                """
                INSERT INTO agent_messages (
                    message_id, case_id, sequence_no, context_revision, sender_type,
                    message_kind, content, structured_payload, idempotency_key, created_at
                ) VALUES (
                    :message_id, :case_id, :sequence, :revision, :sender,
                    :kind, :content, :payload, :idempotency_key, :created_at
                )
                """
            ),
            {
                "message_id": str(uuid.uuid4()),
                "case_id": case_id,
                "sequence": sequence,
                "revision": context_revision,
                "sender": sender_type,
                "kind": message_kind,
                "content": content,
                "payload": _json(payload),
                "idempotency_key": idempotency_key,
                "created_at": created_at,
            },
        )

    def _insert_attempt(
        self,
        connection: Any,
        case: CaseRecord,
        result: str,
        failure_code: str | None,
        now: str,
    ) -> tuple[str, int]:
        attempt_no = int(
            connection.execute(
                text("SELECT COUNT(*) + 1 FROM agent_attempts WHERE case_id = :case_id"),
                {"case_id": case.case_id},
            ).scalar_one()
        )
        attempt_id = str(uuid.uuid4())
        connection.execute(
            text(
                """
                INSERT INTO agent_attempts (
                    attempt_id, case_id, attempt_no, context_revision,
                    result, failure_code, started_at, finished_at
                ) VALUES (
                    :attempt_id, :case_id, :attempt_no, :revision,
                    :result, :failure_code, :now, :now
                )
                """
            ),
            {
                "attempt_id": attempt_id,
                "case_id": case.case_id,
                "attempt_no": attempt_no,
                "revision": case.context_revision,
                "result": result,
                "failure_code": failure_code,
                "now": now,
            },
        )
        return attempt_id, attempt_no

    def _record_json_artifact(self, case_id: str, artifact_type: str, payload: dict[str, Any]) -> None:
        case = self.get_case(case_id)
        with self.engine.begin() as connection:
            self._insert_json_artifact_tx(connection, case, None, artifact_type, payload, _now())

    def _insert_json_artifact_tx(
        self,
        connection: Any,
        case: CaseRecord,
        attempt_id: str | None,
        artifact_type: str,
        payload: dict[str, Any],
        now: str,
    ) -> None:
        content = (_json(payload) or "{}").encode("utf-8")
        artifact_id = str(uuid.uuid4())
        self._insert_artifact(
            connection,
            artifact_id=artifact_id,
            case_id=case.case_id,
            attempt_id=attempt_id,
            artifact_type=artifact_type,
            storage_ref=f"agent-payload://{artifact_type}/{artifact_id}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type="application/json",
            now=now,
        )

    def _insert_file_artifact(
        self,
        connection: Any,
        case: CaseRecord,
        attempt_id: str,
        artifact_type: str,
        path: Path,
        now: str,
    ) -> None:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        self._insert_artifact(
            connection,
            artifact_id=str(uuid.uuid4()),
            case_id=case.case_id,
            attempt_id=attempt_id,
            artifact_type=artifact_type,
            storage_ref=str(path),
            sha256=digest.hexdigest(),
            size_bytes=path.stat().st_size,
            media_type="application/octet-stream" if path.suffix.casefold() == ".zp" else "application/json",
            now=now,
        )

    @staticmethod
    def _insert_artifact(
        connection: Any,
        *,
        artifact_id: str,
        case_id: str,
        attempt_id: str | None,
        artifact_type: str,
        storage_ref: str,
        sha256: str,
        size_bytes: int,
        media_type: str,
        now: str,
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO agent_artifacts (
                    artifact_id, case_id, attempt_id, artifact_type,
                    storage_ref, sha256, size_bytes, media_type, created_at
                ) VALUES (
                    :artifact_id, :case_id, :attempt_id, :artifact_type,
                    :storage_ref, :sha256, :size_bytes, :media_type, :now
                )
                """
            ),
            {
                "artifact_id": artifact_id,
                "case_id": case_id,
                "attempt_id": attempt_id,
                "artifact_type": artifact_type,
                "storage_ref": storage_ref,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "media_type": media_type,
                "now": now,
            },
        )

    def _create_notification(self, connection: Any, case: CaseRecord, summary: str, now: str) -> None:
        connection.execute(
            text(
                """
                INSERT INTO agent_notifications (
                    notification_id, case_id, kind, active, title, summary, created_at
                ) VALUES (
                    :notification_id, :case_id, 'NEEDS_USER', 1, :title, :summary, :now
                )
                """
            ),
            {
                "notification_id": str(uuid.uuid4()),
                "case_id": case.case_id,
                "title": f"Agent Case {case.case_id[:8]} needs input",
                "summary": summary,
                "now": now,
            },
        )

    @staticmethod
    def _resolve_notifications(connection: Any, case_id: str, now: str) -> None:
        connection.execute(
            text(
                """
                UPDATE agent_notifications
                SET active = 0, resolved_at = :now
                WHERE case_id = :case_id AND active = 1
                """
            ),
            {"case_id": case_id, "now": now},
        )

    @staticmethod
    def _require_version(case: CaseRecord, expected_version: int) -> None:
        if case.version != expected_version:
            raise AgentImportError("AGENT_CASE_VERSION_CONFLICT", "Agent Case changed concurrently.", status_code=409)


_default_service: CaseService | None = None


def get_case_service() -> CaseService:
    global _default_service
    if _default_service is None:
        _default_service = CaseService()
    return _default_service
