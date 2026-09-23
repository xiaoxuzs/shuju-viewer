"""Thin orchestration for Agent analysis, controlled ZP execution, and approval."""

from __future__ import annotations

import re
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.agent_import.binary_executor import BinaryExecutionResult, execute_binary_plan
from app.agent_import.case_service import CaseRecord, CaseService, get_case_service
from app.agent_import.contracts import AgentCandidatePlan, AgentPlanReview
from app.agent_import.errors import AgentImportError
from app.agent_import.failure_policy import classify_agent_failure
from app.agent_import.model_provider import AgentModelContext, AgentModelProvider, get_agent_model_provider
from app.agent_import.mapping_preflight import preflight_mapping_plan
from app.agent_import.source_sampling import summarize_source_root
from app.agent_import.states import CaseStatus
from app.agent_zp.service import AgentZpError, import_agent_zp_candidate, stage_agent_zp_candidate
from app.core.db import SessionLocal
from app.fingerprint import compute_dataset_metadata_fingerprint
from app.schemas.agent_zp import AgentZpImportCreateIn, AgentZpImportOut


BinaryExecutor = Callable[..., BinaryExecutionResult]
CandidateImporter = Callable[[CaseRecord, AgentZpImportCreateIn], AgentZpImportOut]
CandidateStager = Callable[[CaseRecord, BinaryExecutionResult, AgentCandidatePlan], dict[str, Any]]


class AgentImportWorkflow:
    def __init__(
        self,
        *,
        service: CaseService | None = None,
        provider: AgentModelProvider | None = None,
        binary_executor: BinaryExecutor | None = None,
        candidate_importer: CandidateImporter | None = None,
        candidate_stager: CandidateStager | None = None,
    ) -> None:
        self.service = service or get_case_service()
        self.provider = provider or get_agent_model_provider()
        self.binary_executor = binary_executor or execute_binary_plan
        self.candidate_importer = candidate_importer or _import_candidate
        self.candidate_stager = candidate_stager or _stage_candidate

    def run_case(self, case_id: str) -> CaseRecord:
        try:
            while True:
                case = self.service.get_case(case_id)
                if case.status == CaseStatus.STOPPING:
                    return self.service.finish_stopping(case_id)
                if case.status in {CaseStatus.CREATED, CaseStatus.ANALYZING}:
                    self.run_analysis_phase(case_id)
                    continue
                if case.status == CaseStatus.STRATEGY_READY:
                    self.run_candidate_phase(case_id)
                    continue
                if case.status == CaseStatus.BUILDING:
                    self.run_review_phase(case_id)
                    continue
                if case.status == CaseStatus.VERIFYING:
                    return self.run_execution_phase(case_id)
                return case
        except Exception as exc:  # noqa: BLE001 - failures are routed into the deterministic Case state
            return self.handle_failure(case_id, exc)

    def handle_failure(self, case_id: str, exc: Exception) -> CaseRecord:
        current = self.service.get_case(case_id)
        if current.status == CaseStatus.STOPPING:
            return self.service.finish_stopping(case_id)
        code = str(getattr(exc, "code", "AGENT_ATTEMPT_FAILED"))
        return self.service.record_failure(
            case_id,
            code=code,
            summary=_safe_failure_summary(exc),
            failure_class=classify_agent_failure(exc),
            diagnostics=getattr(exc, "diagnostics", None),
        )

    def run_analysis_phase(self, case_id: str) -> CaseRecord:
        case = self.service.start_analysis(case_id)
        summary = summarize_source_root(case.source_ref)
        strategy = self.provider.analyze_source(self._context(case, summary))
        return self.service.save_strategy(case_id, strategy)

    def run_candidate_phase(self, case_id: str) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.status != CaseStatus.STRATEGY_READY or case.strategy_payload is None:
            raise AgentImportError(
                "AGENT_STRATEGY_MISSING",
                "Agent candidate generation requires a persisted strategy.",
                status_code=409,
            )
        summary = summarize_source_root(case.source_ref)
        context = self._context(case, summary)
        plan = self.provider.build_candidate(context, case.strategy_payload)
        if case.analysis_category != "AUTO" and plan.analysis_category != case.analysis_category:
            raise ValueError("Agent candidate cannot change the user-selected analysis_category")
        if plan.status != "READY":
            return self.service.record_candidate_needs_user(case_id, plan)
        return self.service.save_candidate(case_id, plan)

    def run_review_phase(self, case_id: str) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.status != CaseStatus.BUILDING or case.strategy_payload is None or case.candidate_payload is None:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "Agent review requires persisted strategy and candidate artifacts.",
                status_code=409,
            )
        plan = AgentCandidatePlan.model_validate(case.candidate_payload)
        preflight = preflight_mapping_plan(
            source_root=case.source_ref,
            plan=plan,
            allow_legacy_mapping=False,
            trusted_observations=_trusted_observations(
                case.strategy_payload,
                _user_message_contents(self.service, case.case_id),
            ),
        )
        review_candidate = getattr(self.provider, "review_candidate", None)
        if not callable(review_candidate):
            raise AgentImportError(
                "AGENT_REVIEW_PROVIDER_MISSING",
                "Agent 1 review is required before deterministic execution.",
                status_code=503,
            )
        summary = summarize_source_root(case.source_ref)
        review = review_candidate(
            self._context(case, summary),
            case.strategy_payload,
            plan,
            preflight,
        )
        reviewed = self.service.save_review(case_id, review)
        if review.status != "APPROVED":
            return reviewed
        return self.service.start_verification(case_id)

    def run_execution_phase(self, case_id: str) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.status != CaseStatus.VERIFYING or case.candidate_payload is None:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "Deterministic execution requires a persisted candidate plan.",
                status_code=409,
            )
        plan = AgentCandidatePlan.model_validate(case.candidate_payload)
        _assert_source_unchanged(case)
        result = self.binary_executor(
            case_id=case_id,
            source_root=case.source_ref,
            source_fingerprint=case.dataset_fingerprint,
            plan=plan,
            trusted_observations=_trusted_observations(
                case.strategy_payload,
                _user_message_contents(self.service, case.case_id),
            ),
        )
        staging = self.candidate_stager(case, result, plan)
        semantic_verification = dict(result.semantic_verification)
        semantic_verification["viewer_staging"] = staging.get("verification")
        if staging.get("capability_report") is not None:
            semantic_verification["dataset_capability_report"] = staging["capability_report"]
        result = replace(result, semantic_verification=semantic_verification)
        return self.service.record_ready(case_id, result)

    def approve_case(self, case_id: str, *, expected_version: int) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.version != expected_version:
            raise AgentImportError("AGENT_CASE_VERSION_CONFLICT", "Agent Case changed concurrently.", status_code=409)
        if case.status != CaseStatus.READY_FOR_REVIEW:
            raise AgentImportError("AGENT_CASE_STATE_CONFLICT", "Case is not ready for approval.", status_code=409)
        _assert_source_unchanged(case)
        if not case.candidate_payload or not case.candidate_zp_path:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "Approved Case has no validated ZP candidate.",
                status_code=409,
            )
        plan = AgentCandidatePlan.model_validate(case.candidate_payload)
        if plan.status != "READY" or plan.zp_conversion_plan is None:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "Approved Case has no executable ZP plan.",
                status_code=409,
            )
        try:
            zp_path = Path(case.candidate_zp_path).resolve(strict=True)
        except OSError as exc:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "The reviewed ZP candidate is no longer available.",
                status_code=409,
            ) from exc
        slug = _dataset_slug(case)
        body = AgentZpImportCreateIn(
            source_path=str(zp_path),
            slug=slug,
            name=Path(case.source_ref).name or plan.source_profile,
            description=f"Agent-imported {plan.source_profile} dataset",
            analysis_category=plan.physical_analysis_mode or plan.analysis_category,
            source_profile=plan.source_profile,
            binary_operation="register_existing_zp",
            format_version=plan.zp_conversion_plan.target_format_version,
            replace_existing=False,
        )
        try:
            imported = self.candidate_importer(case, body)
        except AgentZpError as exc:
            raise AgentImportError(exc.code, exc.message, status_code=exc.status_code) from exc
        return self.service.mark_success(
            case_id,
            dataset_id=imported.dataset_id,
            dataset_slug=imported.dataset_slug,
            capability_report=getattr(imported, "capability_report", None),
        )

    def _context(self, case: CaseRecord, source_summary: dict[str, Any]) -> AgentModelContext:
        user_messages = [
            message.content
            for message in self.service.list_messages(case.case_id)
            if message.sender_type == "USER"
        ]
        return AgentModelContext(
            case_id=case.case_id,
            context_revision=case.context_revision,
            source_root=case.source_ref,
            analysis_category=case.analysis_category,
            requested_source_profile=case.source_profile,
            format_details=case.format_details,
            dataset_fingerprint=case.dataset_fingerprint,
            source_summary=source_summary,
            user_messages=user_messages[-20:],
            candidate_diagnostic_sink=lambda payload: self.service.record_candidate_diagnostic(
                case.case_id, context_revision=case.context_revision, payload=payload,
            ),
        )


def _import_candidate(case: CaseRecord, body: AgentZpImportCreateIn) -> AgentZpImportOut:
    with SessionLocal() as session:
        return import_agent_zp_candidate(
            session,
            body,
            case_id=case.case_id,
            expected_sha256=case.candidate_zp_sha256,
            source_fingerprint=case.dataset_fingerprint,
        )


def _stage_candidate(
    case: CaseRecord,
    result: BinaryExecutionResult,
    plan: AgentCandidatePlan,
) -> dict[str, Any]:
    body = AgentZpImportCreateIn(
        source_path=str(result.zp_path),
        slug=f"agent-staging-{case.case_id}",
        name=f"Agent staging {case.case_id[:8]}",
        description="Transient Agent candidate verification",
        analysis_category=plan.physical_analysis_mode or plan.analysis_category,
        source_profile=plan.source_profile,
        binary_operation="register_existing_zp",
        format_version=result.format_version,
        replace_existing=False,
    )
    with SessionLocal() as session:
        staged = stage_agent_zp_candidate(
            session,
            body,
            case_id=case.case_id,
            expected_sha256=result.output_sha256,
            source_fingerprint=case.dataset_fingerprint,
        )
    return {
        "verification": staged.verification,
        "capability_report": staged.capability_report,
    }


def _dataset_slug(case: CaseRecord) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", Path(case.source_ref).name.casefold()).strip("-") or "agent-dataset"
    return f"{base[:140]}-{case.case_id[:8]}"


def _safe_failure_summary(exc: Exception) -> str:
    code = str(getattr(exc, "code", type(exc).__name__))
    public_message = getattr(exc, "message", None)
    if isinstance(public_message, str) and public_message.strip():
        return f"{code}: {public_message.strip()}"
    return f"{code}: the controlled Agent attempt failed; inspect the Case evidence and provide missing format details."


def _assert_source_unchanged(case: CaseRecord) -> None:
    try:
        current = compute_dataset_metadata_fingerprint(case.source_ref).fingerprint
    except (OSError, ValueError) as exc:
        raise AgentImportError(
            "SOURCE_CHANGED",
            "The Case source root is no longer readable or stable.",
            status_code=409,
        ) from exc
    if current != case.dataset_fingerprint:
        raise AgentImportError(
            "SOURCE_CHANGED",
            "The source directory changed after this Agent Case was created; start a new analysis revision.",
            status_code=409,
        )


def _trusted_observations(
    strategy: dict[str, Any] | None,
    user_messages: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    observations = strategy.get("observations") if isinstance(strategy, dict) else []
    for item in observations if isinstance(observations, list) else []:
        if not isinstance(item, dict):
            continue
        call_id = item.get("call_id")
        digest = item.get("result_sha256")
        payload = item.get("payload")
        if not isinstance(call_id, str) or not isinstance(digest, str) or not isinstance(payload, dict):
            continue
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() == digest:
            result[call_id] = payload
    for index, message in enumerate(user_messages or [], 1):
        result[f"user-message:{index}"] = {"kind": "user_input", "text": message}
    return result


def _user_message_contents(service: CaseService, case_id: str) -> list[str]:
    return [
        item.content
        for item in service.list_messages(case_id)
        if item.sender_type == "USER"
    ][-20:]
