from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
import pytest

from app.agent_import.case_service import CaseService
from app.agent_import.errors import AgentImportError
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.states import CaseStatus
from app.agent_import.workflow import AgentImportWorkflow


def _case(tmp_path: Path, name: str):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / f'{name}.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / name
    source.mkdir()
    (source / "data.tsv").write_text("value\n1\n", encoding="utf-8")
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint="a" * 32,
        analysis_category="AUTO",
        source_profile="unknown",
        format_details=None,
    )
    return service, service.start_analysis(case.case_id)


def test_infrastructure_failure_does_not_consume_scientific_attempt(tmp_path: Path) -> None:
    service, case = _case(tmp_path, "infra")
    workflow = AgentImportWorkflow(service=service)

    failed = workflow.handle_failure(case.case_id, TimeoutError("model timed out"))

    assert failed.status == CaseStatus.FAILED
    assert failed.autonomous_attempt_used == 0
    assert failed.verification_payload["failure_class"] == "INFRASTRUCTURE"
    assert service.list_notifications()[0].kind == "FAILED"


def test_scientific_ambiguity_waits_for_user_without_consuming_attempt(tmp_path: Path) -> None:
    service, case = _case(tmp_path, "ambiguous")
    workflow = AgentImportWorkflow(service=service)
    error = AgentImportError("UNIT_AMBIGUOUS", "Confirm whether RT is seconds or minutes.")

    waiting = workflow.handle_failure(case.case_id, error)

    assert waiting.status == CaseStatus.NEEDS_USER
    assert waiting.autonomous_attempt_used == 0
    assert waiting.verification_payload["failure_class"] == "USER_INPUT"


def test_mapping_failure_consumes_scientific_attempt_and_retries(tmp_path: Path) -> None:
    service, case = _case(tmp_path, "mapping")
    workflow = AgentImportWorkflow(service=service)

    retry = workflow.handle_failure(case.case_id, ValueError("mapping mismatch"))

    assert retry.status == CaseStatus.ANALYZING
    assert retry.autonomous_attempt_used == 1
    assert retry.verification_payload["failure_class"] == "SCIENTIFIC"


def test_exhausted_deterministic_preflight_does_not_restart_source_research(tmp_path):
    service, case = _case(tmp_path, "preflight-exhausted")
    failed = AgentImportWorkflow(service=service).handle_failure(case.case_id,
        AgentImportError("DECLARATIVE_PLAN_INVALID", "Rejected unsupported join after finite plan repair"))
    assert failed.status == CaseStatus.FAILED
    assert failed.autonomous_attempt_used == 0
    assert failed.verification_payload["failure_class"] == "ENGINEERING_REVIEW"


def test_identical_failure_with_unchanged_evidence_stops_instead_of_research_loop(tmp_path):
    service, case = _case(tmp_path, "no-progress")
    workflow = AgentImportWorkflow(service=service)
    assert workflow.handle_failure(case.case_id, ValueError("mapping mismatch")).status == CaseStatus.ANALYZING
    failed = workflow.handle_failure(case.case_id, ValueError("mapping mismatch"))
    assert failed.status == CaseStatus.FAILED
    assert failed.verification_payload["failure_code"] == "ENGINEERING_NO_PROGRESS"
    assert len([a for a in service.list_artifacts(case.case_id) if a.artifact_type == "failure_progress"]) == 2


@pytest.mark.parametrize("guided", [False, True])
def test_candidate_schema_exhaustion_is_engineering_error_with_saved_proposals(tmp_path: Path, monkeypatch, guided) -> None:
    from app.agent_import import model_provider

    service, case = _case(tmp_path, "candidate")
    workflow = AgentImportWorkflow(service=service)
    if guided:
        waiting = workflow.handle_failure(case.case_id, AgentImportError("UNIT_AMBIGUOUS", "Confirm unit"))
        case = service.submit_user_answer(
            case.case_id, content="confirm unit:rt=minute", expected_version=waiting.version, idempotency_key="answer-1",
        )
    monkeypatch.setattr(model_provider.settings, "openai_api_key", "test-key")
    from app.agent_import.model_routing import model_route_identity
    strategy = service.save_strategy(case.case_id, {"blueprint": {}, "observations": [], "model_route_identity": model_route_identity()})
    monkeypatch.setattr(model_provider, "_chat_json", lambda **kw: {
        "status": "READY", "analysis_category": "BOTTOM_UP", "source_profile": "unknown",
    })
    with pytest.raises(AgentImportError) as error:
        workflow.run_candidate_phase(case.case_id)
    failed = workflow.handle_failure(case.case_id, error.value)

    assert failed.status == CaseStatus.FAILED
    assert failed.autonomous_attempt_used == 0
    assert failed.verification_payload["failure_class"] == "ENGINEERING_REVIEW"
    assert failed.verification_payload["diagnostics"]["candidate_attempt"] == 3
    diagnostics = [item for item in service.list_artifacts(case.case_id) if item.artifact_type == "candidate_diagnostic"]
    assert len(diagnostics) == 3
    assert all(item.structured_payload["context_revision"] == strategy.context_revision for item in diagnostics)
    assert service.list_messages(case.case_id)[-1].message_kind == "EVIDENCE"
