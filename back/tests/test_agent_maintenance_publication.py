"""Real ZP/SQL/ASGI repair publication; application/browser receipts are synthetic."""
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from test_agent_zp_import import isolated_agent_zp_settings
from test_semantic_zp_projection import _plan
from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentImportError
from app.agent_import.input_assets import freeze_source, hash_file
from app.agent_import.maintenance import MaintenanceFeedback, MaintenanceDecision, submit_feedback, list_feedback
from app.agent_import.maintenance_consumer import consume_once
from app.agent_import.maintenance_publication import list_revisions, rollback_revision
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.research_tools import AgentResearchToolbox
from app.agent_import.source_code import canonical_bytes, digest_bytes
from app.agent_import.verification import seal_record
from app.agent_import.delivery import validate_candidate_application as real_application_validation
from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation
from app.agent_zp.service import import_agent_zp_candidate
from app.api.v1 import build_api_router
from app.core.config import settings
from app.core.db import engine, SessionLocal
from app.declarative_ingest import build_declarative_zp_artifact
from app.fingerprint import compute_dataset_metadata_fingerprint
from app.schemas.agent_zp import AgentZpImportCreateIn


@pytest.fixture
def repair(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_model_authorization_required", False)
    monkeypatch.setattr(settings, "agent_input_snapshot_enabled", True)
    monkeypatch.setattr(settings, "agent_candidate_verification_enabled", True)
    monkeypatch.setattr(settings, "agent_revision_reads_enabled", True)
    monkeypatch.setattr(settings, "viewer_build_id", "b" * 64)
    monkeypatch.setattr(settings, "agent_verification_signing_key", "synthetic-publication-test-signing-key")
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    monkeypatch.setattr(settings, "agent_verification_oracle_root", oracle_root)
    ensure_agent_import_schema(engine)
    # The universal fixture recycles SQLite dataset IDs; reset only test-owned
    # revision controls between these synthetic publication scenarios.
    with engine.begin() as db:
        for table in ("dataset_revision_events", "dataset_revision_heads", "dataset_revisions"):
            db.execute(text(f"DELETE FROM {table}"))
    service = CaseService(engine)
    root = settings.resolved_data_root / "source"
    root.mkdir()
    (root / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\na\tr1\tPEPTIDE\tP1\t42\n")
    fingerprint = compute_dataset_metadata_fingerprint(root).fingerprint
    case = service.create_case(source_ref=str(root), dataset_fingerprint=fingerprint, analysis_category="BOTTOM_UP", source_profile="example", format_details=None)
    snapshot = freeze_source(root, settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source")
    observation = AgentResearchToolbox(root).execute("inspect_source_file", {"relative_path": "results.tsv"})
    declarative = _plan(with_fasta=False).model_dump(mode="json")
    for item in declarative["field_mappings"]:
        item["evidence_refs"] = ["source"]
    candidate = AgentCandidatePlan(schema_version=3, analysis_category="BOTTOM_UP", source_profile="example", binary_operation="convert_declared_mapping_to_zp",
        zp_conversion_plan={"relative_source": "results.tsv", "declarative_plan": declarative})
    original = build_declarative_zp_artifact(source_root=root, source_fingerprint=fingerprint, plan=candidate.zp_conversion_plan.declarative_plan,
        output_path=settings.resolved_zp_output_root / "original.zp")
    with SessionLocal() as db:
        imported = import_agent_zp_candidate(db, AgentZpImportCreateIn(source_path=str(original.path), slug="repair-fixture", name="Repair fixture",
            analysis_category="BOTTOM_UP", source_profile="example", binary_operation="register_existing_zp"), case_id=case.case_id, source_fingerprint=fingerprint)
    requirements = "c" * 64
    contract = FullAcceptanceContract(source_identity=snapshot["sha256"], requirements_sha256=requirements,
        source_evidence="Independent synthetic TSV contract", scope="one complete synthetic row", source_roles={"results.tsv": "identifications"},
        table=TableExpectation(relative_path="results.tsv", reader="delimited", id_column="id", run_column="run", sequence_column="sequence",
            proteins_column="proteins", quantity_column="intensity", quantity_unit="source_intensity", semantics_evidence="Fixture quantity is identification intensity, no labelled channels."))
    (oracle_root / f"{snapshot['sha256']}-{requirements}.json").write_text(contract.model_dump_json(), encoding="utf-8")
    strategy = {"input_snapshot": snapshot, "requirements_sha256": requirements, "observations": [
        {"call_id": "source", "payload": observation, "result_sha256": digest_bytes(canonical_bytes(observation))}]}
    with engine.begin() as db:
        db.execute(text("""UPDATE agent_import_cases SET status='SUCCESS',ever_published=1,dataset_id=:dataset,dataset_slug=:slug,
            candidate_payload=:candidate,candidate_zp_path=:path,candidate_zp_sha256=:sha,strategy_payload=:strategy WHERE case_id=:id"""),
            {"dataset": imported.dataset_id, "slug": imported.dataset_slug, "candidate": candidate.model_dump_json(), "path": str(original.path),
             "sha": original.output_sha256, "strategy": json.dumps(strategy), "id": case.case_id})
    repaired = candidate.model_dump(mode="json")
    repaired["zp_conversion_plan"]["declarative_plan"]["plan_id"] = "repaired-display-v2"
    repaired["zp_conversion_plan"]["declarative_plan"]["requested_views"] = [{"view_id": "bu.matches"}, {"view_id": "bu.proteins"}]
    decision = MaintenanceDecision(status="MAPPING_PLAN", explanation="Synthetic display repair", candidate=repaired)
    monkeypatch.setattr("app.agent_import.maintenance_consumer.propose_maintenance_plan", lambda context: decision)
    def application_receipt(context, candidate_path, **kwargs):
        assert kwargs["input_root"].is_dir()
        return seal_record({"status": "PASSED", "code_sha256": settings.viewer_build_id, "source_sha256": snapshot["sha256"],
            "candidate_sha256": hash_file(candidate_path), "browser_assertions": ["synthetic application boundary"],
            "import_result": {"synthetic": True}, "cleanup": {"processes_stopped": True}}, settings.agent_verification_signing_key.encode())
    monkeypatch.setattr("app.agent_import.delivery.validate_candidate_application", application_receipt)
    yield service, service.get_case(case.case_id)


def test_feedback_publishes_then_http_reads_new_revision_and_rollback(repair, monkeypatch):
    service, parent = repair
    from app.agent_import.import_recipes import SaveRecipe, save_recipe
    original_recipe = save_recipe(service, parent.case_id, SaveRecipe(name="Reusable example"))
    from app.agent_import.maintenance_publication import publish_repair
    failures = []
    def observed_publication(*args):
        try:
            return publish_repair(*args)
        except Exception as exc:
            import traceback
            failures.append(traceback.format_exc())
            raise
    monkeypatch.setattr("app.agent_import.maintenance_publication.publish_repair", observed_publication)
    task = submit_feedback(service, parent.case_id, MaintenanceFeedback(feedback="Improve the display", idempotency_key="repair-publish-000001"))
    assert consume_once(service)
    assert not failures, failures
    result = next(row for row in list_feedback(service, parent.case_id) if row["task_id"] == task["task_id"])
    assert result["state"] == "PUBLISHED", result["wait_reason"]
    history = list_revisions(service, parent.case_id)
    assert len(history["revisions"]) == 2
    assert result["candidate_sha256"] != parent.candidate_zp_sha256
    updated_recipe = save_recipe(service, parent.case_id, SaveRecipe(name="Reusable example", recipe_id=original_recipe["recipe_id"], expected_version=1))
    assert updated_recipe["version"] == 2 and updated_recipe["maintenance_task_id"] == task["task_id"]
    assert json.loads(updated_recipe["candidate_json"])["zp_conversion_plan"]["declarative_plan"]["plan_id"] == "repaired-display-v2"
    app = FastAPI()
    app.include_router(build_api_router())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(f"/api/v1/datasets/{parent.dataset_slug}/capability-report")
        assert response.status_code == 200, response.text
        assert response.headers["x-viewer-revision"] == result["published_revision_id"]
        from app.api.v1.zp_conversions import router as zp_router
        app.include_router(zp_router, prefix="/api/v1")
        status = client.get(f"/api/v1/datasets/{parent.dataset_id}/zp-status")
        assert status.status_code == 200, status.text
        assert status.json()["assets"][0]["output_sha256"] == result["candidate_sha256"]
        prior = next(row["revision_id"] for row in history["revisions"] if row["state"] == "RETIRED")
        rollback_revision(service, parent.case_id, prior, result["published_revision_id"])
        assert client.get(f"/api/v1/datasets/{parent.dataset_slug}/capability-report").headers["x-viewer-revision"] == prior
        pinned = client.get(f"/api/v1/datasets/{parent.dataset_slug}/capability-report", headers={"X-Viewer-Revision": result["published_revision_id"]})
        assert pinned.status_code == 200 and pinned.headers["x-viewer-revision"] == result["published_revision_id"]
    assert service.get_case(parent.case_id).status.value == "SUCCESS"
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM datasets")).scalar() == 1


def test_failed_application_check_never_activates_repair(repair, monkeypatch):
    service, parent = repair
    def failed(*args, **kwargs):
        raise AgentImportError("APPLICATION_VALIDATION_FAILED", "Synthetic failed browser boundary")
    monkeypatch.setattr("app.agent_import.delivery.validate_candidate_application", failed)
    task = submit_feedback(service, parent.case_id, MaintenanceFeedback(feedback="Improve the display", idempotency_key="repair-failure-000001"))
    assert consume_once(service)
    result = next(row for row in list_feedback(service, parent.case_id) if row["task_id"] == task["task_id"])
    assert result["state"] == "FAILED" and result["wait_reason"] == "APPLICATION_VALIDATION_FAILED"
    assert list_revisions(service, parent.case_id)["active_revision_id"] == "legacy"


def test_repair_uses_retained_source_after_original_folder_is_moved(repair, monkeypatch):
    service, parent = repair
    from app.agent_import.maintenance_publication import publish_repair
    failures = []
    def observed_publication(*args):
        try:
            return publish_repair(*args)
        except Exception:
            import traceback
            failures.append(traceback.format_exc())
            raise
    monkeypatch.setattr("app.agent_import.maintenance_publication.publish_repair", observed_publication)
    source = Path(parent.source_ref)
    source.rename(source.with_name("moved-original"))
    task = submit_feedback(service, parent.case_id, MaintenanceFeedback(feedback="Improve the display", idempotency_key="retained-source-repair-01"))
    assert consume_once(service)
    assert not failures, failures
    result = next(row for row in list_feedback(service, parent.case_id) if row["task_id"] == task["task_id"])
    assert result["state"] == "PUBLISHED", result["wait_reason"]


def test_cancelled_validated_candidate_cannot_be_activated_through_rollback(repair, monkeypatch):
    from app.agent_import.revisions import RevisionStore
    service, parent = repair
    sealed = []
    original_seal = RevisionStore.seal
    def cancel_after_sealing(store, revision, *args, **kwargs):
        receipt = original_seal(store, revision, *args, **kwargs)
        sealed.append(revision)
        raise AgentImportError("AGENT_CANCELLED", "Synthetic cancellation after validation")
    monkeypatch.setattr(RevisionStore, "seal", cancel_after_sealing)
    submit_feedback(service, parent.case_id, MaintenanceFeedback(feedback="Improve the display", idempotency_key="cancel-before-publication-01"))
    assert consume_once(service)
    assert sealed and list_revisions(service, parent.case_id)["active_revision_id"] == "legacy"
    with pytest.raises(AgentImportError) as failure:
        rollback_revision(service, parent.case_id, sealed[0], "legacy")
    assert failure.value.code == "REVISION_NOT_READABLE"


@pytest.mark.skipif(os.environ.get("VIEWER_REAL_REPAIR_VERIFICATION") != "1", reason="Requires explicit isolated PostgreSQL/browser verification")
def test_real_application_verifier_publishes_repair(repair, monkeypatch):
    from app.agent_import.source_code import SourceSnapshot
    from shutil import which
    service, parent = repair
    project = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(settings, "agent_source_root", project)
    monkeypatch.setattr(settings, "viewer_build_id", SourceSnapshot.capture(project).identity)
    monkeypatch.setattr(settings, "agent_api_worker_enabled", False)
    monkeypatch.setattr(settings, "agent_verification_postgres_bin", project / "cjb/runtime/postgresql/bin")
    monkeypatch.setattr(settings, "agent_verification_node", Path(which("node")))
    monkeypatch.setattr(settings, "agent_verification_browser_cache", Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    monkeypatch.setattr("app.agent_import.delivery.validate_candidate_application", real_application_validation)
    task = submit_feedback(service, parent.case_id, MaintenanceFeedback(feedback="Improve the display", idempotency_key="real-repair-verifier-001"))
    assert consume_once(service)
    result = next(row for row in list_feedback(service, parent.case_id) if row["task_id"] == task["task_id"])
    assert result["state"] == "PUBLISHED", result["wait_reason"]
