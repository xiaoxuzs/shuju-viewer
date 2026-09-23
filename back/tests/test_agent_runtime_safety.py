from __future__ import annotations

import socket
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.case_service import CaseService
from app.agent_import.execution_control import ExecutionFence, checkpoint, execution_scope
from app.agent_import.errors import AgentImportError
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.public_documents import PublicDocuments, public_target
from app.agent_import.research_tools import AgentResearchToolbox
from app.agent_import.source_code import SourceSnapshot
from app.core.config import settings


def source(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "back/app").mkdir(parents=True)
    (root / "back/app/current.py").write_text("def current():\n    return 'dirty implementation'\n", encoding="utf-8")
    (root / "back/.env").write_text("API_KEY=must-not-copy", encoding="utf-8")
    (root / "back/app/.env.local").write_text("secret", encoding="utf-8")
    return root


def test_snapshot_includes_working_copy_and_untracked_but_not_secrets(tmp_path):
    root = source(tmp_path)
    snapshot = SourceSnapshot.capture(root)
    assert list(snapshot.manifest) == ["back/app/current.py"]
    destination = tmp_path / "candidate"
    snapshot.export(destination)
    assert (destination / "back/app/current.py").read_text() == (root / "back/app/current.py").read_text()
    assert not (destination / "back/.env").exists()
    (root / "back/app/current.py").write_text("changed", encoding="utf-8")
    assert SourceSnapshot.capture(root).identity != snapshot.identity
    assert snapshot.read("back/app/current.py")["lines"][0]["text"] == "def current():"
    with pytest.raises(ValueError):
        snapshot.export(destination)


@pytest.mark.parametrize("path", ["../back/.env", "back/.env", "C:/private.py", "back/app/current.py:secret", "back\\app\\current.py"])
def test_source_read_refuses_escape_or_sensitive_paths(tmp_path, path):
    snapshot = SourceSnapshot.capture(source(tmp_path))
    with pytest.raises(ValueError):
        snapshot.read(path)


def test_source_tools_are_explicit_and_bound_to_snapshot(tmp_path):
    root = source(tmp_path)
    snapshot = SourceSnapshot.capture(root)
    assert "read_viewer_source" not in AgentResearchToolbox(root).names
    tools = AgentResearchToolbox(root, source_snapshot=snapshot)
    result = tools.execute("search_viewer_source", {"query": "current"})
    assert result["snapshot_sha256"] == snapshot.identity
    assert result["hits"][0]["line"] == 1
    assert {item["function"]["name"] for item in tools.definitions()} == tools.names


@pytest.mark.parametrize("url", ["http://example.org/docs", "https://user:secret@example.org/a", "https://example.org/a?q=private", "https://example.org:8443/a"])
def test_public_docs_reject_unapproved_url_shapes(url):
    with pytest.raises(ValueError):
        public_target(url)


def test_public_docs_refuse_private_resolution_and_unknown_document(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        public_target("https://public.example/docs")
    with pytest.raises(ValueError, match="catalog"):
        PublicDocuments({}).read("not-approved")


def service(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'case.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    svc = CaseService(engine)
    case = svc.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
                          analysis_category="BOTTOM_UP", source_profile="test", format_details=None)
    return svc, case


def fence_for(svc, case):
    return ExecutionFence(case.case_id, case.lease_token, lambda amount: svc.check_execution(case.case_id, case.lease_token, amount))


def test_stale_worker_cannot_register_strategy_after_takeover(tmp_path):
    svc, original = service(tmp_path)
    first = svc.claim_next(worker_id="one")
    svc.start_analysis(original.case_id)
    with svc.engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET lease_expires_at = '2000-01-01T00:00:00+00:00'"))
    second = svc.claim_next(worker_id="two")
    assert first.lease_token != second.lease_token
    with execution_scope(fence_for(svc, first)), pytest.raises(AgentImportError) as exc:
        svc.save_strategy(original.case_id, {"bad": "stale output"})
    assert exc.value.code == "WORKER_LEASE_LOST"
    assert svc.get_case(original.case_id).strategy_payload is None


def test_cancel_blocks_execution_and_result_registration(tmp_path):
    svc, original = service(tmp_path)
    claimed = svc.claim_next(worker_id="one")
    svc.start_analysis(original.case_id)
    svc.request_stop(original.case_id)
    with execution_scope(fence_for(svc, claimed)):
        with pytest.raises(AgentImportError, match="cancellation"):
            checkpoint()
        with pytest.raises(AgentImportError):
            svc.save_strategy(original.case_id, {"bad": "cancelled output"})
        assert svc.finish_stopping(original.case_id).status.value == "STOPPED"


def test_released_lease_rejects_late_strategy_even_before_another_claim(tmp_path):
    svc, original = service(tmp_path)
    claimed = svc.claim_next(worker_id="one")
    svc.start_analysis(original.case_id)
    with svc.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET lease_owner=NULL,lease_expires_at=NULL WHERE case_id=:id"), {"id": original.case_id})
    with execution_scope(fence_for(svc, claimed)), pytest.raises(AgentImportError) as exc:
        svc.save_strategy(original.case_id, {"late": True})
    assert exc.value.code == "WORKER_LEASE_LOST"


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows junction attack surface")
def test_actual_windows_junction_cannot_enter_source_snapshot(tmp_path, monkeypatch):
    import _winapi
    root = source(tmp_path)
    outside = tmp_path / "synthetic-outside"
    outside.mkdir()
    (outside / "private.py").write_text("synthetic fixture; no personal files")
    junction = root / "back/app/linked"
    _winapi.CreateJunction(str(outside), str(junction))
    assert junction.is_junction()
    with pytest.raises(ValueError, match="Linked"):
        SourceSnapshot.capture(root)
    from app.core.config import _resolved_test_data_root
    monkeypatch.setattr("app.core.config.tempfile.gettempdir", lambda: str(root))
    with pytest.raises(RuntimeError, match="temporary"):
        _resolved_test_data_root(junction)
    assert (outside / "private.py").read_text() == "synthetic fixture; no personal files"


def test_case_budget_is_shared_across_claims_and_deadline_does_not_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_case_token_budget", 1000)
    svc, original = service(tmp_path)
    first = svc.claim_next(worker_id="one")
    with execution_scope(fence_for(svc, first)):
        checkpoint(700)
    with svc.engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET lease_expires_at = '2000-01-01T00:00:00+00:00'"))
        old_deadline = connection.scalar(text("SELECT deadline_at FROM agent_import_cases"))
    second = svc.claim_next(worker_id="two")
    with execution_scope(fence_for(svc, second)), pytest.raises(AgentImportError) as exc:
        checkpoint(301)
    assert exc.value.code == "TASK_RUN_LIMIT_REACHED"
    with svc.engine.connect() as connection:
        assert connection.scalar(text("SELECT deadline_at FROM agent_import_cases")) == old_deadline
