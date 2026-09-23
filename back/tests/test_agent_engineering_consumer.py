import json

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.case_service import CaseService
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.worker import AgentWorker
from app.agent_import.workflow import AgentImportWorkflow
from app.core.config import settings
from sqlalchemy import create_engine, text


class UnitProvider:
    proposed = False
    def analyze_source(self, context):
        return {"schema_version": 1, "decision": "READY_FOR_CANDIDATE", "analysis_category": "BOTTOM_UP", "proposed_source_profile": "unit", "binary_operation": "register_existing_zp", "relative_source": "none.zp"}
    def build_candidate(self, context, strategy):
        return AgentCandidatePlan(status="UNSUPPORTED", analysis_category="BOTTOM_UP", source_profile="unit", questions=["Unit-test capability gap"])
    def propose_engineering_change(self, context, gap, artifact_id, snapshot, allowed):
        from app.agent_import.engineering import EngineeringChange
        self.proposed = True
        path = next(iter(allowed))
        return EngineeringChange(case_id=context.case_id, context_revision=context.context_revision, gap_artifact_id=artifact_id,
            baseline_sha256=snapshot.identity, decision_role="initial_implementation", semantics="Unit fake-runner test only",
            changes=[{"path": path, "before_sha256": snapshot.manifest[path]["sha256"], "content": "value=2\n"}], checks=["backend_tests"])


def prepare(tmp_path, monkeypatch, runner=None):
    monkeypatch.setattr(settings, "agent_engineering_enabled", True)
    source = tmp_path / "input"
    source.mkdir()
    (source / "input.txt").write_text("fixture")
    repo = tmp_path / "repo"
    (repo / "back/app/bu").mkdir(parents=True)
    (repo / "back/app/bu/feature.py").write_text("value=1\n")
    monkeypatch.setattr(settings, "agent_source_root", repo)
    monkeypatch.setattr(settings, "agent_implementation_source_evidence_enabled", True)
    monkeypatch.setattr(settings, "agent_engineering_allowed_paths_json", json.dumps(["back/app/bu/feature.py"]))
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(source), dataset_fingerprint="a" * 32, analysis_category="BOTTOM_UP", source_profile="unit", format_details=None)
    provider = UnitProvider()
    workflow = AgentImportWorkflow(service=service, provider=provider, engineering_runner=runner)
    return AgentWorker(service=service, workflow=workflow), service, case, provider, repo


def test_real_worker_graph_consumes_gap_and_refuses_without_sandbox(tmp_path, monkeypatch):
    worker, service, case, provider, repo = prepare(tmp_path, monkeypatch)
    assert worker.poll_once()
    current = service.get_case(case.case_id)
    assert current.status.value == "FAILED"
    assert current.verification_payload["failure_code"] == "SANDBOX_NOT_ADMITTED"
    assert not provider.proposed
    assert any(a.artifact_type == "engineering_gate" for a in service.list_artifacts(case.case_id))
    assert (repo / "back/app/bu/feature.py").read_text() == "value=1\n"
    assert not worker.poll_once()


def test_fake_runner_lifecycle_records_output_but_cannot_activate_or_publish(tmp_path, monkeypatch):
    class FakeRunner:
        def require_admission(self):
            return "test fake, not real isolation evidence"
        def run(self, *_args, **_kwargs):
            return {"status": "EXECUTED_NOT_ACCEPTED", "exit_code": 0, "scope": "unit fake runner"}
    worker, service, case, provider, repo = prepare(tmp_path, monkeypatch, FakeRunner())
    worker.poll_once()
    current = service.get_case(case.case_id)
    assert provider.proposed
    assert current.verification_payload["failure_code"] == "ENGINEERING_ACCEPTANCE_REQUIRED"
    assert current.dataset_id is None and current.ever_published is False
    assert (repo / "back/app/bu/feature.py").read_text() == "value=1\n"
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM agent_engineering_operations")) == 1
    assert not worker.poll_once()
