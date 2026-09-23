from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.authorization_ledger import AuthorizationLedger, route_identity
from app.agent_import.errors import AgentImportError


@pytest.fixture
def ledger(tmp_path):
    clock = [1000.0]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'authority.sqlite'}", connect_args={"timeout": 10})
    value = AuthorizationLedger(engine, clock=lambda: clock[0])
    value.ensure_schema()
    value.register("grant", {"request_limit": 4, "reservation_limit": 10000, "active_seconds": 100,
        "experiment_seconds": 60, "output_limit": 500, "route_sha256": route_identity("https://fixture.invalid/v1/chat/completions", "fixture"),
        "roles": ["research", "implementation", "maintenance"], "authorization_basis": "isolated test, no external calls"})
    experiment = value.begin_experiment("grant", "fixture", 60)
    lineage = value.bind_case("grant", "case", "source", call_limit=4, unit_limit=10000)
    yield value, clock, experiment, lineage
    engine.dispose()


def reserve(value, experiment, lineage, role="research"):
    return value.reserve("grant", experiment, lineage, role=role,
        route_sha256=route_identity("https://fixture.invalid/v1/chat/completions", "fixture"),
        request_bytes=100, output_limit=100, request_sha256="a" * 64)


def test_concurrent_reservations_are_committed_before_send_and_never_refunded(ledger):
    value, _, experiment, lineage = ledger
    def call(_):
        try:
            return reserve(value, experiment, lineage)[0]
        except AgentImportError as exc:
            assert exc.code == "MODEL_AUTHORIZATION_EXHAUSTED"
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        requests = [v for v in pool.map(call, range(12)) if v]
    assert len(requests) == 4
    value.finish_request(requests[0], outcome="UNKNOWN", result={"connection_lost": True})
    reopened = AuthorizationLedger(value.engine, clock=value.clock)
    assert reopened.status("grant")["calls_used"] == 4
    with pytest.raises(AgentImportError, match="exhausted"):
        reserve(reopened, experiment, lineage)


def test_activity_is_union_and_unreconciled_crash_is_not_a_pause(ledger):
    value, clock, first, lineage = ledger
    clock[0] += 10
    second = value.begin_experiment("grant", "parallel", 60)
    clock[0] += 20
    value.end_experiment("grant", first, "confirmed processes stopped")
    clock[0] += 10
    assert value.status("grant")["active_seconds"] == 40
    clock[0] += 40
    assert value.status("grant")["active_seconds"] == 80
    with pytest.raises(AgentImportError, match="exhausted"):
        value.check("grant", second, lineage)


def test_children_cannot_wash_original_budget_or_publication_history(ledger):
    value, _, experiment, parent = ledger
    with value.engine.begin() as db:
        db.execute(text("UPDATE agent_authorized_lineages SET published=1,call_limit=1 WHERE lineage_id=:id"), {"id": parent})
    child = value.bind_case("grant", "maintenance-case", "source", parent=parent, call_limit=10, unit_limit=10000)
    with pytest.raises(AgentImportError) as error:
        reserve(value, experiment, child, "implementation")
    assert error.value.code == "PUBLISHED_CASE_ROLE_FORBIDDEN"
    reserve(value, experiment, child, "maintenance")
    with pytest.raises(AgentImportError, match="exhausted"):
        reserve(value, experiment, child, "maintenance")


def test_unknown_and_conflicting_results_keep_the_reservation(ledger):
    value, _, experiment, lineage = ledger
    request, _ = reserve(value, experiment, lineage)
    value.finish_request(request, outcome="ERROR", result={"type": "TimeoutError"})
    value.finish_request(request, outcome="ERROR", result={"type": "TimeoutError"})
    with pytest.raises(AgentImportError):
        value.finish_request(request, outcome="RESPONSE", result={"success": True})
    assert value.status("grant")["reserved_units"] == 200


def test_preview_is_persistent_across_tool_instances_and_requests(ledger):
    value, _, experiment, lineage = ledger
    value.charge_preview("grant", experiment, lineage, 131072)
    with pytest.raises(AgentImportError):
        AuthorizationLedger(value.engine, clock=value.clock).charge_preview("grant", experiment, lineage, 1)
    child = value.bind_case("grant", "child", "source", parent=lineage, call_limit=4, unit_limit=10000)
    with pytest.raises(AgentImportError):
        value.charge_preview("grant", experiment, child, 1)
    with value.engine.connect() as db:
        assert db.execute(text("SELECT preview_used FROM agent_authorized_lineages WHERE lineage_id=:id"), {"id": child}).scalar() == 0


def test_unregistered_route_revoked_expired_and_ended_requests_fail_closed(ledger):
    value, _, experiment, lineage = ledger
    with pytest.raises(AgentImportError):
        value.reserve("grant", experiment, lineage, role="research", route_sha256="b"*64, request_bytes=1, output_limit=1, request_sha256="a"*64)
    assert value.status("grant")["calls_used"] == 0
    value.end_experiment("grant", experiment, "stopped")
    with pytest.raises(AgentImportError):
        reserve(value, experiment, lineage)
    value.revoke("grant")
    with pytest.raises(AgentImportError):
        value.begin_experiment("grant", "not allowed", 1)


def test_real_transport_guard_runs_before_child_creation(monkeypatch):
    from app.agent_import import model_http
    from app.core.config import settings
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    monkeypatch.setattr(model_http, "_bounded_child", lambda *a, **kw: pytest.fail("transport must not be reached"))
    with pytest.raises(AgentImportError) as error:
        model_http.request_model_json("https://fixture.invalid/v1/chat/completions", method="POST", api_key="synthetic", body={"model": "fixture", "max_completion_tokens": 10}, timeout=5)
    assert error.value.code == "TASK_RUNTIME_REQUIRED"
