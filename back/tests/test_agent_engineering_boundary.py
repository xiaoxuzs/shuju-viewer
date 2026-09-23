import pytest

from app.agent_import.engineering import EngineeringChange, apply_change
from app.agent_import.errors import AgentImportError
from app.agent_import.sandbox_runner import DockerPolicy, DockerSandboxRunner
from app.agent_import.source_code import SourceSnapshot


def fixture(tmp_path):
    app = tmp_path / "back/app/bu"
    app.mkdir(parents=True)
    (app / "display.py").write_text("value = 'uncommitted'\n")
    snapshot = SourceSnapshot.capture(tmp_path)
    change = EngineeringChange(gap_artifact_id="gap", case_id="case", context_revision=1,
        baseline_sha256=snapshot.identity, decision_role="initial_implementation", semantics="Display only",
        changes=[{"path": "back/app/bu/display.py", "before_sha256": snapshot.manifest["back/app/bu/display.py"]["sha256"],
                  "content": "value = 'candidate'\n"}], checks=["backend_tests"])
    return snapshot, change


def test_engineering_uses_actual_preimage_and_never_mutates_worktree(tmp_path):
    snapshot, change = fixture(tmp_path)
    result = apply_change(snapshot, change, allowed_paths=frozenset({"back/app/bu/display.py"}), ever_published=False)
    assert snapshot.identity != result.identity
    assert "uncommitted" in (tmp_path / "back/app/bu/display.py").read_text()
    assert change.operation_key == change.operation_key
    with pytest.raises(ValueError, match="baseline"):
        apply_change(result, change, allowed_paths=frozenset({"back/app/bu/display.py"}), ever_published=False)
    with pytest.raises(ValueError, match="Published"):
        apply_change(snapshot, change, allowed_paths=frozenset({"back/app/bu/display.py"}), ever_published=True)


@pytest.mark.parametrize("path", ["../outside.py", "back/.env", "back/tests/test_gate.py", "back/app/agent_import/verification.py", "back/app/declarative_ingest/preflight.py"])
def test_patch_cannot_modify_credentials_or_acceptance_rules(tmp_path, path):
    snapshot, change = fixture(tmp_path)
    with pytest.raises(ValueError):
        changed = change.model_copy(update={"changes": [change.changes[0].model_copy(update={"path": path, "before_sha256": None})]})
        apply_change(snapshot, changed, allowed_paths=frozenset({path}), ever_published=False)


def test_docker_command_has_no_host_credentials_network_or_control_socket(tmp_path, monkeypatch):
    executable = tmp_path / "docker.exe"
    executable.write_bytes(b"not-executed")
    policy = DockerPolicy(executable=executable, engine="npipe:////./pipe/docker_engine", image="sha256:" + "a" * 64)
    runner = DockerSandboxRunner(policy)
    command = runner.command(tmp_path, "viewer-engineering-" + "b" * 32, "backend_tests")
    assert "--network=none" in command and "--read-only" in command and "--pull=never" in command
    assert sum("type=bind" in value for value in command) == 1
    snapshot, _ = fixture(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("unadmitted execution"))
    with pytest.raises(AgentImportError) as failure:
        runner.run(snapshot, tmp_path / "new", operation_key="a" * 64, check="backend_tests")
    assert failure.value.code == "SANDBOX_NOT_ADMITTED"
    assert not (tmp_path / "new").exists()


def test_engineering_ledger_reuses_case_fence_and_refuses_repeat(tmp_path):
    from test_agent_runtime_safety import service, fence_for
    from app.agent_import.execution_control import execution_scope
    from app.agent_import.engineering import execute_engineering_change
    from sqlalchemy import text
    svc, case = service(tmp_path)
    claimed = svc.claim_next(worker_id="engineering-test")
    snapshot, change = fixture(tmp_path)
    change = change.model_copy(update={"case_id": case.case_id})
    class RejectingRunner:
        def run(self, *_args, **_kwargs):
            raise AgentImportError("SANDBOX_NOT_ADMITTED", "No isolated runner", status_code=403)
    args = dict(runner=RejectingRunner(), allowed_paths=frozenset({"back/app/bu/display.py"}), output_root=tmp_path / "output")
    with execution_scope(fence_for(svc, claimed)):
        result = execute_engineering_change(svc, change, snapshot, **args)
        assert result["state"] == "BLOCKED"
        with pytest.raises(AgentImportError, match="ledger"):
            execute_engineering_change(svc, change, snapshot, **args)
    with svc.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM agent_engineering_operations")) == 1
    assert not (tmp_path / "output").exists()


def test_cancelled_engineering_operation_cannot_register_late_result(tmp_path):
    from test_agent_runtime_safety import service, fence_for
    from app.agent_import.execution_control import execution_scope
    from app.agent_import.engineering import execute_engineering_change
    from sqlalchemy import text
    svc, case = service(tmp_path)
    claimed = svc.claim_next(worker_id="engineering-test")
    snapshot, change = fixture(tmp_path)
    change = change.model_copy(update={"case_id": case.case_id})
    class CancellingFakeRunner:
        def run(self, *_args, **_kwargs):
            with svc.engine.begin() as connection:
                connection.execute(text("UPDATE agent_import_cases SET stop_requested_at='requested' WHERE case_id=:id"), {"id": case.case_id})
            return {"exit_code": 0}  # fake control-flow result, never real sandbox evidence
    with execution_scope(fence_for(svc, claimed)), pytest.raises(AgentImportError) as failure:
        execute_engineering_change(svc, change, snapshot, runner=CancellingFakeRunner(),
            allowed_paths=frozenset({"back/app/bu/display.py"}), output_root=tmp_path / "output")
    assert failure.value.code == "AGENT_CANCELLED"
    with svc.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM agent_engineering_operations")) == "RUNNING"
    assert not any(a.artifact_type == "engineering_execution" for a in svc.list_artifacts(case.case_id))
