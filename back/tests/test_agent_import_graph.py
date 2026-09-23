from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine

from app.agent_import.binary_executor import BinaryExecutionResult
from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan, AgentPlanReview
from app.agent_import.graph import AgentImportGraphRunner
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.states import CaseStatus
from app.agent_import.workflow import AgentImportWorkflow
from app.fingerprint import compute_dataset_metadata_fingerprint


class _Provider:
    def __init__(self) -> None:
        self.needs_user = False
        self.analysis_calls = 0
        self.candidate_calls = 0

    def analyze_source(self, context):
        self.analysis_calls += 1
        return {"decision": "READY", "case_id": context.case_id}

    def build_candidate(self, context, strategy):
        del strategy
        self.candidate_calls += 1
        if self.needs_user:
            return AgentCandidatePlan(
                schema_version=3,
                status="NEEDS_USER",
                analysis_category=context.analysis_category,
                source_profile=context.requested_source_profile,
                questions=["Confirm the ambiguous run identity."],
            )
        return AgentCandidatePlan(
            schema_version=1,
            analysis_category=context.analysis_category,
            source_profile=context.requested_source_profile,
            binary_operation="register_existing_zp",
            zp_conversion_plan={"relative_source": "candidate.zp", "target_format_version": 3},
        )

    def review_candidate(self, context, strategy, candidate, preflight):
        del context, strategy, candidate, preflight
        return AgentPlanReview(status="APPROVED", evidence=["test review"])


def _runner(tmp_path: Path, provider: _Provider):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'graph.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "candidate.zp").write_bytes(b"input")
    fingerprint = compute_dataset_metadata_fingerprint(source).fingerprint
    output = tmp_path / "validated.zp"
    output.write_bytes(b"validated")
    certificate = tmp_path / "deep.json"
    certificate.write_text("{}", encoding="utf-8")
    workflow = AgentImportWorkflow(
        service=service,
        provider=provider,
        binary_executor=lambda **_kwargs: BinaryExecutionResult(
            zp_path=output,
            output_sha256="b" * 64,
            format_version=3,
            validation_mode="deep",
            validation_certificate_path=certificate,
            source_fingerprint=fingerprint,
        ),
        candidate_stager=lambda _case, _result, _plan: {
            "verification": {"readable_run_count": 1},
            "capability_report": None,
        },
    )
    runner = AgentImportGraphRunner(
        service=service,
        workflow=workflow,
        checkpointer=InMemorySaver(),
    )
    return service, source, fingerprint, runner


def test_graph_runs_explicit_phases_to_review_boundary(tmp_path: Path) -> None:
    provider = _Provider()
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="unknown",
        format_details=None,
    )

    ready = runner.run_case(case.case_id)

    assert ready.status == CaseStatus.READY_FOR_REVIEW
    assert provider.analysis_calls == 1
    assert provider.candidate_calls == 1


def test_graph_interrupts_and_resumes_after_committed_user_answer(tmp_path: Path) -> None:
    provider = _Provider()
    provider.needs_user = True
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="unknown",
        format_details=None,
    )

    waiting = runner.run_case(case.case_id)
    assert waiting.status == CaseStatus.NEEDS_USER
    assert len(service.list_notifications()) == 1

    answered = service.submit_user_answer(
        case.case_id,
        content="The run is run-a.",
        expected_version=waiting.version,
        idempotency_key="answer-1",
    )
    provider.needs_user = False
    restarted_runner = AgentImportGraphRunner(
        service=service,
        workflow=runner.workflow,
        checkpointer=runner.checkpointer,
    )
    resumed = restarted_runner.run_case(case.case_id)

    assert answered.context_revision == 2
    assert resumed.status == CaseStatus.READY_FOR_REVIEW
    assert provider.analysis_calls == 2
    assert provider.candidate_calls == 2


def test_worker_claims_persisted_intermediate_state_after_lease_loss(tmp_path: Path) -> None:
    provider = _Provider()
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="unknown",
        format_details=None,
    )
    strategy_ready = runner.workflow.run_analysis_phase(case.case_id)
    assert strategy_ready.status == CaseStatus.STRATEGY_READY

    claimed = service.claim_next(worker_id="replacement-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed.case_id == case.case_id
    assert claimed.status == CaseStatus.STRATEGY_READY
    assert service.renew_lease(case.case_id, worker_id="replacement-worker", lease_seconds=30) is True


def test_reverify_existing_candidate_never_reinvokes_research_or_implementation(tmp_path):
    import pytest
    from app.agent_import.task_retry import reverify_candidate
    from app.agent_import.errors import AgentImportError
    provider = _Provider()
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(source_ref=str(source), dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY", source_profile="unknown", format_details=None)
    ready = runner.run_case(case.case_id)
    with pytest.raises(AgentImportError):
        reverify_candidate(service, case.case_id, ready.version - 1)
    queued = reverify_candidate(service, case.case_id, ready.version)
    assert queued.status == CaseStatus.VERIFYING
    checked = runner.run_case(case.case_id)
    assert checked.status == CaseStatus.READY_FOR_REVIEW
    assert checked.candidate_zp_sha256 == ready.candidate_zp_sha256
    assert checked.context_revision == ready.context_revision
    assert (provider.analysis_calls, provider.candidate_calls) == (1, 1)


def test_review_rejection_repairs_in_original_graph_without_research_or_user_question(tmp_path):
    class Provider(_Provider):
        reviews = 0
        def review_candidate(self, *args):
            self.reviews += 1
            return AgentPlanReview(status="REJECTED", issues=["Fix an implementation issue"]) if self.reviews == 1 else AgentPlanReview(status="APPROVED", evidence=["Corrected fixture plan"])
    provider = Provider()
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(source_ref=str(source), dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY", source_profile="unknown", format_details=None)
    result = runner.run_case(case.case_id)
    assert result.status == CaseStatus.READY_FOR_REVIEW
    assert provider.analysis_calls == 1 and provider.candidate_calls == 2 and provider.reviews == 2
    assert not any(m.structured_payload and m.structured_payload.get("event") == "review_needs_user" for m in service.list_messages(case.case_id))


def test_repeated_review_rejection_stops_without_human_fact_question(tmp_path):
    class Provider(_Provider):
        def review_candidate(self, *args):
            return AgentPlanReview(status="REJECTED", issues=["Same implementation issue"])
    provider = Provider()
    service, source, fingerprint, runner = _runner(tmp_path, provider)
    case = service.create_case(source_ref=str(source), dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY", source_profile="unknown", format_details=None)
    result = runner.run_case(case.case_id)
    assert result.status == CaseStatus.FAILED
    assert result.verification_payload["failure_code"] == "REVIEW_NO_PROGRESS"
    assert provider.analysis_calls == 1 and provider.candidate_calls == 2
