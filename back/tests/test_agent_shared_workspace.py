"""Ordinary shared access has no login; internal authority and origin checks remain."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.agent_import import api as routes
from app.agent_import.case_service import CaseService
from app.agent_import.migrations import ensure_agent_import_schema
from app.core.config import settings


@pytest.fixture
def shared(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "table.tsv").write_text("id\tvalue\na\t0\n")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'control.sqlite'}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(settings, "data_root", source)
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    monkeypatch.setattr(settings, "agent_internal_token", None)
    monkeypatch.setattr(settings, "agent_browser_sessions_enabled", False)
    monkeypatch.setattr(settings, "agent_auto_delivery_enabled", False)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    with TestClient(app, base_url="http://localhost:5173", client=("127.0.0.1", 51000)) as client:
        yield client, service, source
    engine.dispose()


def test_blank_default_import_and_shared_read_need_no_identity(shared):
    client, service, source = shared
    created = client.post("/api/v1/agent-import-cases/from-path", json={"source_path": str(source)}, headers={"Origin": "http://localhost:5173"})
    assert created.status_code == 201, created.text
    case = service.get_case(created.json()["case_id"])
    assert case.analysis_category == "AUTO" and case.source_profile == "Unknown format" and case.format_details is None
    assert case.owner_id == "shared-workspace" and case.status.value == "CREATED"
    assert client.get("/api/v1/agent-import-cases/"+case.case_id).status_code == 200
    with service.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agent_authorizations")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM agent_browser_sessions")).scalar() == 0
    assert service.claim_next(worker_id="ordinary").case_id == case.case_id


@pytest.mark.parametrize("headers", [{"Origin": "https://attacker.invalid"}, {"Host": "attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}])
def test_origin_and_host_checks_are_not_removed(shared, headers):
    client, service, source = shared
    response = client.post("/api/v1/agent-import-cases/from-path", json={"source_path": str(source)}, headers=headers)
    assert response.status_code == 403 and response.json()["detail"]["code"] == "WORKSPACE_ORIGIN_REJECTED"
    assert not service.list_cases()


def test_high_privilege_routes_and_publication_policy_stay_protected(shared):
    client, service, source = shared
    assert client.get("/api/v1/agent-retention/dry-run").status_code == 403
    assert client.post("/api/v1/agent-import-cases/absent/recover-execution", json={"expected_version": 1, "new_code_identity": "a"*64}).status_code == 403
    response = client.post("/api/v1/agent-import-cases/from-path", json={"source_path": str(source), "delivery_policy": "auto_test"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "AUTO_DELIVERY_NOT_AUTHORIZED"
    assert not service.list_cases()
