"""Thin orchestration for Agent analysis, controlled ZP execution, and approval."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agent_import.binary_executor import BinaryExecutionResult, execute_binary_plan
from app.agent_import.case_service import CaseRecord, CaseService, get_case_service
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentImportError
from app.agent_import.model_provider import AgentModelContext, AgentModelProvider, get_agent_model_provider
from app.agent_import.source_sampling import summarize_source_root
from app.agent_import.states import CaseStatus
from app.agent_zp.service import AgentZpError, import_agent_zp_candidate
from app.core.db import SessionLocal
from app.schemas.agent_zp import AgentZpImportCreateIn, AgentZpImportOut


BinaryExecutor = Callable[..., BinaryExecutionResult]
CandidateImporter = Callable[[CaseRecord, AgentZpImportCreateIn], AgentZpImportOut]


class AgentImportWorkflow:
    def __init__(
        self,
        *,
        service: CaseService | None = None,
        provider: AgentModelProvider | None = None,
        binary_executor: BinaryExecutor | None = None,
        candidate_importer: CandidateImporter | None = None,
    ) -> None:
        self.service = service or get_case_service()
        self.provider = provider or get_agent_model_provider()
        self.binary_executor = binary_executor or execute_binary_plan
        self.candidate_importer = candidate_importer or _import_candidate

    def run_case(self, case_id: str) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.status == CaseStatus.STOPPING:
            return self.service.finish_stopping(case_id)
        try:
            case = self.service.start_analysis(case_id)
            summary = summarize_source_root(case.source_ref)
            context = self._context(case, summary)
            strategy = self.provider.analyze_source(context)
            case = self.service.save_strategy(case_id, strategy)
            context = self._context(case, summary)
            plan = self.provider.build_candidate(context, strategy)
            if plan.analysis_category != case.analysis_category:
                raise ValueError("Agent candidate cannot change the user-selected analysis_category")
            case = self.service.save_candidate(case_id, plan)
            self.service.start_verification(case_id)
            result = self.binary_executor(
                case_id=case_id,
                source_root=case.source_ref,
                source_fingerprint=case.dataset_fingerprint,
                plan=plan,
            )
            return self.service.record_ready(case_id, result)
        except Exception as exc:  # noqa: BLE001 - failures are routed into the deterministic Case state
            current = self.service.get_case(case_id)
            if current.status == CaseStatus.STOPPING:
                return self.service.finish_stopping(case_id)
            code = str(getattr(exc, "code", "AGENT_ATTEMPT_FAILED"))
            return self.service.record_failure(
                case_id,
                code=code,
                summary=_safe_failure_summary(exc),
            )

    def approve_case(self, case_id: str, *, expected_version: int) -> CaseRecord:
        case = self.service.get_case(case_id)
        if case.version != expected_version:
            raise AgentImportError("AGENT_CASE_VERSION_CONFLICT", "Agent Case changed concurrently.", status_code=409)
        if case.status != CaseStatus.READY_FOR_REVIEW:
            raise AgentImportError("AGENT_CASE_STATE_CONFLICT", "Case is not ready for approval.", status_code=409)
        if not case.candidate_payload or not case.candidate_zp_path:
            raise AgentImportError(
                "AGENT_CANDIDATE_MISSING",
                "Approved Case has no validated ZP candidate.",
                status_code=409,
            )
        plan = AgentCandidatePlan.model_validate(case.candidate_payload)
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
            analysis_category=plan.analysis_category,
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
            analysis_category=case.analysis_category,
            requested_source_profile=case.source_profile,
            format_details=case.format_details,
            dataset_fingerprint=case.dataset_fingerprint,
            source_summary=source_summary,
            user_messages=user_messages[-20:],
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


def _dataset_slug(case: CaseRecord) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", Path(case.source_ref).name.casefold()).strip("-") or "agent-dataset"
    return f"{base[:140]}-{case.case_id[:8]}"


def _safe_failure_summary(exc: Exception) -> str:
    code = str(getattr(exc, "code", type(exc).__name__))
    public_message = getattr(exc, "message", None)
    if isinstance(public_message, str) and public_message.strip():
        return f"{code}: {public_message.strip()}"
    return f"{code}: the controlled Agent attempt failed; inspect the Case evidence and provide missing format details."
