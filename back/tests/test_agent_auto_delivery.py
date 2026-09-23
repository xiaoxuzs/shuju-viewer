from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.case_service import CaseService
from app.agent_import.delivery import require_auto_test_policy
from app.agent_import.errors import AgentImportError
from app.agent_import.execution_control import ExecutionFence, execution_scope
from app.agent_import.graph import _route
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.model_provider import AgentModelContext, ConfiguredAgentModelProvider
from app.agent_import.states import CaseStatus
from app.core.config import settings


def test_auto_delivery_refuses_default_or_production_database(monkeypatch):
    monkeypatch.setattr(settings, "agent_auto_delivery_enabled", True)
    with pytest.raises(AgentImportError) as exc:
        require_auto_test_policy()
    assert exc.value.code == "AUTO_DELIVERY_NOT_AUTHORIZED"


def test_ready_auto_delivery_requires_a_fresh_claim_and_manual_still_waits():
    base = {"case_id": "id", "status": "READY_FOR_REVIEW", "context_revision": 1, "stop_requested": False, "last_error_code": None}
    assert _route({**base, "delivery_policy": "manual", "delivery_claimed": True}) == "end"
    assert _route({**base, "delivery_policy": "auto_test", "delivery_claimed": False}) == "end"
    assert _route({**base, "delivery_policy": "auto_test", "delivery_claimed": True}) == "deliver"


def test_published_context_never_calls_implementation_model(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent_import.model_provider._chat_json", lambda **_: pytest.fail("Agent2 must not be called"))
    context = AgentModelContext(case_id="published", context_revision=2, source_root=str(tmp_path),
        analysis_category="BOTTOM_UP", requested_source_profile="unknown", format_details=None,
        dataset_fingerprint="a" * 32, source_summary={}, user_messages=["fix display"], ever_published=True)
    with pytest.raises(AgentImportError) as exc:
        ConfiguredAgentModelProvider().build_candidate(context, {})
    assert exc.value.code == "PUBLISHED_CASE_ROLE_FORBIDDEN"


def test_source_research_is_not_implicitly_forwarded_to_a_second_model(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent_import.model_provider._chat_json", lambda **_: pytest.fail("No code egress without consent"))
    context = AgentModelContext(case_id="private-source", context_revision=1, source_root=str(tmp_path),
        analysis_category="BOTTOM_UP", requested_source_profile="unknown", format_details=None,
        dataset_fingerprint="a" * 32, source_summary={}, user_messages=[])
    with pytest.raises(AgentImportError) as exc:
        ConfiguredAgentModelProvider().build_candidate(context, {"observations": [{"tool_name": "read_viewer_source"}]})
    assert exc.value.code == "SOURCE_EVIDENCE_EGRESS_NOT_AUTHORIZED"


def test_local_deadline_is_not_misreported_as_provider_http_rejection(tmp_path, monkeypatch):
    def expire(**_kwargs):
        raise AgentImportError("AGENT_DEADLINE_EXCEEDED", "Local deadline expired", status_code=409)
    monkeypatch.setattr("app.agent_import.model_provider._chat_json", expire)
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-key")
    context = AgentModelContext(case_id="expired", context_revision=1, source_root=str(tmp_path),
        analysis_category="BOTTOM_UP", requested_source_profile="unknown", format_details=None,
        dataset_fingerprint="a" * 32, source_summary={}, user_messages=[])
    with pytest.raises(AgentImportError) as exc:
        ConfiguredAgentModelProvider().build_candidate(context, {})
    assert exc.value.code == "AGENT_DEADLINE_EXCEEDED"


def test_delivery_record_handover_and_case_success_share_transaction(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'case.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
                               analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None)
    claimed = service.claim_next(worker_id="test")
    with engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET status='DELIVERING',candidate_zp_sha256=:sha WHERE case_id=:id"), {"id": case.case_id, "sha": "b" * 64})
    current = service.get_case(case.case_id)
    imported = SimpleNamespace(dataset_id=1, dataset_slug="fixture")
    handover = {"sha256": "c" * 64, "verification_operation": "d" * 64, "markdown": "# Fixture, not an actual scientific validation"}
    with execution_scope(ExecutionFence(case.case_id, claimed.lease_token, lambda _: 60)):
        with pytest.raises(RuntimeError):
            with engine.begin() as connection:
                service.finalize_delivery_transaction(connection, current, imported, handover)
                raise RuntimeError("simulate transaction failure")
        assert service.get_case(case.case_id).status == CaseStatus.DELIVERING
        assert not service.get_case(case.case_id).ever_published
        assert service.list_artifacts(case.case_id) == []
        with engine.begin() as connection:
            service.finalize_delivery_transaction(connection, current, imported, handover)
    complete = service.get_case(case.case_id)
    assert complete.status == CaseStatus.SUCCESS and complete.ever_published
    assert service.list_artifacts(case.case_id)[0].artifact_type == "handover"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM agent_deliveries")) == 1
        assert connection.scalar(text("SELECT ended_at FROM agent_task_runs WHERE task_id=:id"), {"id": case.case_id}) is not None


def test_publication_failure_never_reenters_initial_model_pipeline(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'publication.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
                               analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None)
    with engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET status='DELIVERING' WHERE case_id=:id"), {"id": case.case_id})
    failed = service.record_failure(case.case_id, code="AGENT_ZP_DATASET_FINGERPRINT_EXISTS", summary="Existing logical dataset")
    assert failed.status == CaseStatus.FAILED
    assert failed.autonomous_attempt_used == 0


def test_manual_approval_cancelled_before_commit_cannot_publish(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'manual.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
                               analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None)
    with engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET status='READY_FOR_REVIEW' WHERE case_id=:id"), {"id": case.case_id})
    reviewed = service.get_case(case.case_id)
    service.request_stop(case.case_id)
    with engine.begin() as connection, pytest.raises(AgentImportError):
        service.finalize_reviewed_import_transaction(connection, reviewed, SimpleNamespace(dataset_id=1, dataset_slug="fixture"), None)
    assert service.get_case(case.case_id).status == CaseStatus.STOPPED
    assert not service.get_case(case.case_id).ever_published


def test_manual_success_closes_runtime_in_the_same_transaction(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manual-finish.sqlite'}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
        analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None)
    with engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET status='READY_FOR_REVIEW' WHERE case_id=:id"), {"id": case.case_id})
    reviewed = service.get_case(case.case_id)
    with pytest.raises(RuntimeError):
        with engine.begin() as connection:
            service.finalize_reviewed_import_transaction(connection, reviewed, SimpleNamespace(dataset_id=1, dataset_slug="fixture"), None)
            raise RuntimeError("rollback fixture")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT ended_at FROM agent_task_runs WHERE task_id=:id"), {"id": case.case_id}) is None
    with engine.begin() as connection:
        service.finalize_reviewed_import_transaction(connection, reviewed, SimpleNamespace(dataset_id=1, dataset_slug="fixture"), None)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT ended_at FROM agent_task_runs WHERE task_id=:id"), {"id": case.case_id}) is not None
