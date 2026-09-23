from types import SimpleNamespace
import pytest

from app.agent_import.recovery import recover_execution
from app.agent_import.states import CaseStatus
from app.agent_import.errors import AgentImportError
from app.agent_import.failure_policy import classify_agent_failure, AgentFailureClass
from app.core.config import settings


def setup_gate(monkeypatch, **updates):
    monkeypatch.setattr(settings, "agent_api_worker_enabled", False)
    monkeypatch.setattr(settings, "agent_internal_token", "unit-only-operator-token-00000000000000")
    case = SimpleNamespace(status=CaseStatus.FAILED, version=3, ever_published=False, dataset_id=None,
        deadline_at="2000-01-01T00:00:00+00:00", **updates)
    return SimpleNamespace(get_case=lambda _: case)


def test_expired_original_deadline_cannot_be_reset_for_recovery(monkeypatch):
    service = setup_gate(monkeypatch)
    with pytest.raises(AgentImportError) as error:
        recover_execution(service, "case", expected_version=3, new_code_identity="a" * 64)
    assert error.value.code == "AGENT_DEADLINE_EXCEEDED"


@pytest.mark.parametrize("field,value", [("ever_published", True), ("dataset_id", 1), ("status", CaseStatus.SUCCESS), ("version", 4)])
def test_published_or_concurrent_case_cannot_enter_initial_repair(monkeypatch, field, value):
    service = setup_gate(monkeypatch)
    setattr(service.get_case("case"), field, value)
    with pytest.raises(AgentImportError) as error:
        recover_execution(service, "case", expected_version=3, new_code_identity="a" * 64)
    assert error.value.code == "RECOVERY_STATE_CONFLICT"


def test_execution_mapping_failures_do_not_trigger_full_research_retry():
    error = AgentImportError("DECLARATIVE_EXECUTION_FAILED", "mapping rejected", status_code=422)
    assert classify_agent_failure(error) == AgentFailureClass.ENGINEERING_REVIEW
