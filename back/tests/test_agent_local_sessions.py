import time

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.agent_import import local_sessions as sessions
from app.core.config import settings


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sessions.sqlite'}")
    monkeypatch.setattr(sessions, "session_engine", lambda: engine)
    monkeypatch.setattr(settings, "agent_browser_sessions_enabled", True)
    monkeypatch.setattr(settings, "agent_browser_origin", "http://127.0.0.1:15519")
    token = sessions.create_handoff(engine, origin=settings.agent_browser_origin, subject="owner-a")
    app = FastAPI()
    app.include_router(sessions.router, prefix="/api/v1")
    @app.post("/api/v1/owned", dependencies=[Depends(sessions.guard_upload_session)])
    def owned(request: Request):
        sessions.claim_resource(request, "case", "case-a")
        return {"ok": True}
    @app.get("/api/v1/owned/{case_id}")
    def read(request: Request, case_id: str):
        sessions.authenticate(request)
        sessions.check_resource(request, "case", case_id)
        return {"ok": True}
    client = TestClient(app, base_url=settings.agent_browser_origin, client=("127.0.0.1", 12345))
    yield engine, token, client
    client.close()
    engine.dispose()


def login(client, token):
    result = client.post("/api/v1/local-session/exchange", json={"handoff": token}, headers={"Origin": settings.agent_browser_origin})
    assert result.status_code == 200
    assert "httponly" in result.headers["set-cookie"].lower()
    assert "samesite=strict" in result.headers["set-cookie"].lower()
    return {"Origin": settings.agent_browser_origin, "X-Viewer-CSRF": result.json()["csrf"]}


def test_fresh_browser_exchange_csrf_ownership_and_revoke(runtime):
    engine, token, client = runtime
    assert client.get("/api/v1/owned/case-a").status_code == 401
    headers = login(client, token)
    assert client.post("/api/v1/local-session/exchange", json={"handoff": token}, headers=headers).status_code == 401
    assert client.post("/api/v1/owned", headers={"Origin": settings.agent_browser_origin}).status_code == 403
    assert client.post("/api/v1/owned", headers=headers).status_code == 200
    assert client.get("/api/v1/owned/case-a").status_code == 200
    assert client.get("/api/v1/owned/other-case").status_code == 403
    assert client.post("/api/v1/local-session/revoke", headers=headers).status_code == 200
    assert client.get("/api/v1/owned/case-a").status_code == 401
    with engine.connect() as db:
        assert db.execute(text("SELECT token_hash FROM agent_browser_handoffs")).scalar() != token


@pytest.mark.parametrize("headers", [
    {"Origin": "http://attacker.invalid"}, {"Origin": "http://127.0.0.1:15519", "Host": "attacker.invalid"},
    {"Origin": "http://127.0.0.1:15519", "Sec-Fetch-Site": "cross-site"}, {},
])
def test_wrong_origin_host_cross_site_or_missing_origin_cannot_consume_handoff(runtime, headers):
    _, token, client = runtime
    assert client.post("/api/v1/local-session/exchange", json={"handoff": token}, headers=headers).status_code == 403
    login(client, token)


def test_expired_session_and_other_subject_cannot_read_assets(runtime):
    engine, token, client = runtime
    headers = login(client, token)
    client.post("/api/v1/owned", headers=headers)
    other = sessions.create_handoff(engine, origin=settings.agent_browser_origin, subject="owner-b")
    login(client, other)
    assert client.get("/api/v1/owned/case-a").status_code == 403
    with engine.begin() as db:
        db.execute(text("UPDATE agent_browser_sessions SET expires_at=:past"), {"past": time.time()-1})
    assert client.get("/api/v1/owned/case-a").status_code == 401
