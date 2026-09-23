import pytest
from sqlalchemy import text

from app.agent_import.maintenance import MaintenanceFeedback, submit_feedback, list_feedback, propose_maintenance_plan
from app.agent_import.errors import AgentImportError
from test_agent_failure_policy import _case


def test_feedback_inherits_published_context_without_reopening_case(tmp_path):
    service, case = _case(tmp_path, "published")
    body = MaintenanceFeedback(feedback="The quantity display is incorrect", idempotency_key="feedback-fixture-0001", page="/datasets/source/matches/1")
    with pytest.raises(AgentImportError):
        submit_feedback(service, case.case_id, body)
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='SUCCESS',ever_published=1,dataset_id=7 WHERE case_id=:id"), {"id": case.case_id})
    first = submit_feedback(service, case.case_id, body)
    assert submit_feedback(service, case.case_id, body)["task_id"] == first["task_id"]
    assert first["ever_published"] == 1 and first["dataset_id"] == 7
    assert first["state"] == "QUEUED"
    assert len(list_feedback(service, case.case_id)) == 1
    assert service.get_case(case.case_id).status.value == "SUCCESS"
    with pytest.raises(AgentImportError):
        submit_feedback(service, case.case_id, body.model_copy(update={"feedback": "different issue"}))


def test_maintenance_never_falls_back_to_initial_implementation(monkeypatch):
    from app.agent_import.model_provider import ConfiguredAgentModelProvider
    monkeypatch.setattr(ConfiguredAgentModelProvider, "build_candidate", lambda *a, **kw: pytest.fail("Agent2 is forbidden"))
    monkeypatch.setattr(ConfiguredAgentModelProvider, "propose_engineering_change", lambda *a, **kw: pytest.fail("Initial engineering is forbidden"))
    with pytest.raises(AgentImportError) as error:
        propose_maintenance_plan({"ever_published": True})
    assert error.value.code == "TASK_RUNTIME_REQUIRED"
