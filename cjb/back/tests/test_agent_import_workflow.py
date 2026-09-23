from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.agent_import.errors import AgentImportError
from app.agent_import.binary_executor import BinaryExecutionResult
from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan, AgentPlanReview
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.states import CaseStatus
from app.agent_import.workflow import AgentImportWorkflow
from app.agent_zp.service import AgentZpError
from app.fingerprint import compute_dataset_metadata_fingerprint


class FakeProvider:
    def analyze_source(self, context):
        return {"decision": "READY", "case_id": context.case_id}

    def build_candidate(self, context, strategy):
        return AgentCandidatePlan.model_validate(
            {
                "schema_version": 1,
                "analysis_category": context.analysis_category,
                "source_profile": context.requested_source_profile,
                "binary_operation": "register_existing_zp",
                "zp_conversion_plan": {"relative_source": "candidate.zp", "target_format_version": 3},
            }
        )

    def review_candidate(self, context, strategy, candidate, preflight):
        return AgentPlanReview(status="APPROVED", evidence=["test review"])


def test_workflow_generates_zp_then_waits_for_user_approval(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'agent.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / "unknown"
    source.mkdir()
    (source / "candidate.zp").write_bytes(b"input")
    fingerprint = compute_dataset_metadata_fingerprint(source).fingerprint
    output = tmp_path / "validated.zp"
    output.write_bytes(b"validated")
    certificate = tmp_path / "deep.json"
    certificate.write_text("{}", encoding="utf-8")
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="vendor-zp",
        format_details=None,
    )

    workflow = AgentImportWorkflow(
        service=service,
        provider=FakeProvider(),
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
        candidate_importer=lambda _case, body: SimpleNamespace(dataset_id=91, dataset_slug=body.slug),
    )

    ready = workflow.run_case(case.case_id)
    assert ready.status == CaseStatus.READY_FOR_REVIEW
    assert ready.dataset_id is None
    assert "agent_1_review" in [item.artifact_type for item in service.list_artifacts(case.case_id)]

    def reject_changed_candidate(_case, _body):
        raise AgentZpError("AGENT_ZP_CANDIDATE_CHANGED", status_code=409)

    failing_workflow = AgentImportWorkflow(
        service=service,
        provider=FakeProvider(),
        candidate_importer=reject_changed_candidate,
    )
    with pytest.raises(AgentImportError) as exc_info:
        failing_workflow.approve_case(case.case_id, expected_version=ready.version)
    assert exc_info.value.code == "AGENT_ZP_CANDIDATE_CHANGED"
    assert service.get_case(case.case_id).status == CaseStatus.READY_FOR_REVIEW

    imported = workflow.approve_case(case.case_id, expected_version=ready.version)
    assert imported.status == CaseStatus.SUCCESS
    assert imported.dataset_id == 91
    assert imported.dataset_slug is not None


def test_agent_1_review_can_require_user_input_before_binary_execution(tmp_path: Path) -> None:
    class NeedsUserProvider(FakeProvider):
        def review_candidate(self, context, strategy, candidate, preflight):
            return AgentPlanReview(
                status="NEEDS_USER",
                questions=["Confirm the ambiguous source unit."],
            )

    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'agent-review.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / "unknown-review"
    source.mkdir()
    (source / "candidate.zp").write_bytes(b"input")
    fingerprint = compute_dataset_metadata_fingerprint(source).fingerprint
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="vendor-zp",
        format_details=None,
    )
    executed = False

    def binary_executor(**_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("binary execution must not start")

    waiting = AgentImportWorkflow(
        service=service,
        provider=NeedsUserProvider(),
        binary_executor=binary_executor,
        candidate_stager=lambda _case, _result, _plan: {},
    ).run_case(case.case_id)

    assert waiting.status == CaseStatus.NEEDS_USER
    assert executed is False
    assert len(service.list_notifications()) == 1


def test_approval_rejects_source_changed_after_candidate_review(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'source-change.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / "source-change"
    source.mkdir()
    source_file = source / "candidate.zp"
    source_file.write_bytes(b"input")
    fingerprint = compute_dataset_metadata_fingerprint(source).fingerprint
    output = tmp_path / "source-change-validated.zp"
    output.write_bytes(b"validated")
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint=fingerprint,
        analysis_category="SPECTRA_ONLY",
        source_profile="vendor-zp",
        format_details=None,
    )
    workflow = AgentImportWorkflow(
        service=service,
        provider=FakeProvider(),
        binary_executor=lambda **_kwargs: BinaryExecutionResult(
            zp_path=output,
            output_sha256="b" * 64,
            format_version=3,
            validation_mode="deep",
            validation_certificate_path=None,
            source_fingerprint=fingerprint,
        ),
        candidate_stager=lambda _case, _result, _plan: {"verification": {}, "capability_report": None},
        candidate_importer=lambda _case, _body: (_ for _ in ()).throw(
            AssertionError("changed source must not publish")
        ),
    )
    ready = workflow.run_case(case.case_id)
    source_file.write_bytes(b"changed")

    with pytest.raises(AgentImportError) as exc_info:
        workflow.approve_case(case.case_id, expected_version=ready.version)

    assert exc_info.value.code == "SOURCE_CHANGED"
    assert service.get_case(case.case_id).status == CaseStatus.READY_FOR_REVIEW
