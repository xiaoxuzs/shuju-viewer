"""Positive authorized independent-role consumption; HTTP model transport is fake."""
import hashlib
import json
import time

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.case_service import CaseService
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.maintenance import MaintenanceFeedback, submit_feedback, list_feedback
from app.agent_import.maintenance_consumer import consume_once
from app.agent_import.model_provider import ConfiguredAgentModelProvider
from app.agent_import import model_http
from app.agent_import.research_tools import AgentResearchToolbox
from app.agent_import.source_code import canonical_bytes
from app.core.config import settings
from app.fingerprint import compute_dataset_metadata_fingerprint
from test_semantic_zp_projection import _plan


@pytest.mark.parametrize("decision_state", ["MAPPING_PLAN", "NEEDS_USER", "ENGINEERING_REQUIRED"])
def test_authorized_maintenance_consumes_and_never_calls_initial_role(tmp_path, monkeypatch, decision_state):
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    monkeypatch.setattr(settings, "agent_input_snapshot_enabled", False)
    monkeypatch.setattr(settings, "openai_base_url", "http://127.0.0.1:19999/_test")
    monkeypatch.setattr(settings, "openai_model", "gpt-test-fixture")
    monkeypatch.setattr(settings, "openai_api_key", "fixture-only")
    monkeypatch.setattr(settings, "zp_output_root", tmp_path / "artifacts")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'business.sqlite'}")
    ensure_agent_import_schema(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\na\tr1\tPEPTIDE\tP1\t0\n")
    service = CaseService(engine)
    case = service.create_case(source_ref=str(source), dataset_fingerprint=compute_dataset_metadata_fingerprint(source).fingerprint,
        analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None, owner_id="owner")
    # Explicit fixture published state; not a claim of initial delivery acceptance.
    observation = AgentResearchToolbox(source).execute("inspect_source_file", {"relative_path": "results.tsv"})
    strategy = {"observations": [{"call_id": "observation", "payload": observation, "result_sha256": hashlib.sha256(canonical_bytes(observation)).hexdigest()}]}
    with engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='SUCCESS',ever_published=1,dataset_id=7,strategy_payload=:strategy WHERE case_id=:id"), {"id": case.case_id, "strategy": json.dumps(strategy)})
    task = submit_feedback(service, case.case_id, MaintenanceFeedback(feedback="Check the display mapping", idempotency_key="feedback-000000001"))
    def forbidden(*args, **kwargs):
        pytest.fail("Initial implementation role must never be called")
    monkeypatch.setattr(ConfiguredAgentModelProvider, "build_candidate", forbidden)
    monkeypatch.setattr(ConfiguredAgentModelProvider, "propose_engineering_change", forbidden)
    plan = _plan(with_fasta=False).model_dump(mode="json")
    for item in plan["field_mappings"]:
        item["evidence_refs"] = ["observation"]
        item["unit"] = None
    decision = {"status": decision_state, "explanation": "Synthetic independent maintenance fixture"}
    if decision_state == "MAPPING_PLAN":
        decision["candidate"] = {"schema_version": 3, "status": "READY", "analysis_category": "BOTTOM_UP", "source_profile": "fixture",
            "binary_operation": "convert_declared_mapping_to_zp", "zp_conversion_plan": {"relative_source": "results.tsv", "target_format_version": 3, "declarative_plan": plan}}
    def transport(encoded, **kwargs):
        body = json.loads(encoded)["body"]
        assert "independent published-dataset maintenance" in body["messages"][0]["content"]
        return {"model": "gpt-test-fixture", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(decision)}}]}
    monkeypatch.setattr(model_http, "_bounded_child", transport)
    assert consume_once(service)
    result = list_feedback(service, case.case_id)[0]
    assert result["task_id"] == task["task_id"]
    assert result["state"] == {"MAPPING_PLAN": "AWAITING_REVISION_VALIDATION", "NEEDS_USER": "NEEDS_USER", "ENGINEERING_REQUIRED": "ENGINEERING_BLOCKED"}[decision_state], result["wait_reason"]
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agent_authorizations")).scalar() == 0
        assert db.execute(text("SELECT role FROM agent_task_requests")).scalar_one() == "maintenance"
        assert db.execute(text("SELECT parent_case_id FROM agent_task_runs WHERE task_id=:id"), {"id": task["task_id"]}).scalar_one() == case.case_id
    assert service.get_case(case.case_id).status.value == "SUCCESS"
    if decision_state == "MAPPING_PLAN":
        from pathlib import Path
        assert Path(result["candidate_path"]).is_file() and result["candidate_sha256"]
    assert not consume_once(service)  # terminal planning state must not spend again
    engine.dispose()
