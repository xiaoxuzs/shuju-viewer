"""Saved plans run against fresh inputs without model research or implementation."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentImportError
from app.agent_import.import_recipes import SaveRecipe, save_recipe, list_recipes, bound_recipe, build_recipe_strategy
from app.agent_import.migrations import ensure_agent_import_schema
from app.core.config import settings
from app.fingerprint import compute_dataset_metadata_fingerprint
from test_semantic_zp_projection import _plan
from test_agent_zp_import import isolated_agent_zp_settings


def candidate():
    return AgentCandidatePlan(schema_version=3, analysis_category="BOTTOM_UP", source_profile="Table example",
        binary_operation="convert_declared_mapping_to_zp", zp_conversion_plan={"relative_source": "results.tsv", "declarative_plan": _plan(with_fasta=False)})


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_model_authorization_required", False)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cases.sqlite'}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    root = settings.resolved_data_root / "old"
    root.mkdir()
    (root / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\na\tr1\tPEPTIDE\tP1\t0\n")
    case = service.create_case(source_ref=str(root), dataset_fingerprint=compute_dataset_metadata_fingerprint(root).fingerprint,
        analysis_category="BOTTOM_UP", source_profile="example", format_details=None)
    with engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='SUCCESS',ever_published=1,dataset_id=7,candidate_payload=:plan WHERE case_id=:id"),
            {"id": case.case_id, "plan": candidate().model_dump_json()})
    yield service, case, settings.resolved_data_root
    engine.dispose()


def test_recipe_persists_and_binds_immutable_version_with_fresh_evidence(published):
    service, parent, root = published
    first = save_recipe(service, parent.case_id, SaveRecipe(name="Reusable example"))
    assert save_recipe(service, parent.case_id, SaveRecipe(name="Reusable example"))["recipe_id"] == first["recipe_id"]
    new_root = root / "new"
    new_root.mkdir()
    (new_root / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\nb\tr2\tANOTHER\tP2\t42\n")
    created = service.create_case(source_ref=str(new_root), dataset_fingerprint=compute_dataset_metadata_fingerprint(new_root).fingerprint,
        analysis_category="BOTTOM_UP", source_profile=first["name"], format_details=None, import_recipe=first)
    second = save_recipe(service, parent.case_id, SaveRecipe(name="Updated example", recipe_id=first["recipe_id"], expected_version=1))
    assert second["version"] == 2
    assert bound_recipe(service, created.case_id)["version"] == 1
    strategy = build_recipe_strategy(bound_recipe(service, created.case_id), new_root)
    assert strategy["provider"] == "saved-import-recipe"
    assert strategy["observations"] and strategy["observations"][0]["payload"]["relative_path"] == "results.tsv"
    assert list_recipes(CaseService(service.engine))[0]["version"] == 2


def test_recipe_rejects_wrong_schema_and_tampered_plan(published):
    service, parent, root = published
    recipe = save_recipe(service, parent.case_id, SaveRecipe(name="example"))
    bad_root = root / "wrong"
    bad_root.mkdir()
    (bad_root / "results.tsv").write_text("id\trun\tsequence\tproteins\nwrong\tr1\tPEPTIDE\tP1\n")
    with pytest.raises(AgentImportError):
        build_recipe_strategy(recipe, bad_root)
    recipe["candidate_json"] = json.dumps({**json.loads(recipe["candidate_json"]), "source_profile": "tampered"})
    with pytest.raises(AgentImportError, match="Saved import plan changed"):
        build_recipe_strategy(recipe, Path(parent.source_ref))


def test_recipe_requires_published_delivery_and_rejects_stale_update(published):
    service, parent, _ = published
    recipe = save_recipe(service, parent.case_id, SaveRecipe(name="example"))
    with pytest.raises(AgentImportError) as failure:
        save_recipe(service, parent.case_id, SaveRecipe(name="bad", recipe_id=recipe["recipe_id"], expected_version=2))
    assert failure.value.code == "IMPORT_RECIPE_CONFLICT"
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET ever_published=0,dataset_id=NULL WHERE case_id=:id"), {"id": parent.case_id})
    with pytest.raises(AgentImportError) as failure:
        save_recipe(service, parent.case_id, SaveRecipe(name="not delivered"))
    assert failure.value.code == "IMPORT_RECIPE_REQUIRES_DELIVERY"


def test_saved_recipe_runs_actual_writer_without_any_model_role(published, monkeypatch):
    from app.agent_import.workflow import AgentImportWorkflow
    from app.declarative_ingest import read_semantic_zp
    service, parent, root = published
    monkeypatch.setattr(settings, "agent_input_snapshot_enabled", False)
    monkeypatch.setattr(settings, "agent_candidate_verification_enabled", False)
    recipe = save_recipe(service, parent.case_id, SaveRecipe(name="example"))
    fresh = root / "fresh"
    fresh.mkdir()
    (fresh / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\nb\tr2\tANOTHER\tP2\t42\n")
    case = service.create_case(source_ref=str(fresh), dataset_fingerprint=compute_dataset_metadata_fingerprint(fresh).fingerprint,
        analysis_category="BOTTOM_UP", source_profile="example", format_details=None, import_recipe=recipe)
    class NoModel:
        def analyze_source(self, *args):
            pytest.fail("Saved import must not research the format again")
        def build_candidate(self, *args):
            pytest.fail("Saved import must use its persisted plan")
        def review_candidate(self, *args):
            pytest.fail("Saved import must use deterministic source checks")
    result = AgentImportWorkflow(service=service, provider=NoModel()).run_case(case.case_id)
    assert result.status.value == "READY_FOR_REVIEW", result.verification_payload
    semantic = read_semantic_zp(Path(result.candidate_zp_path))
    assert semantic.identifications[0].source_fields["id"] == "b"


def test_recipe_api_saves_lists_and_queues_fixed_version(published, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.agent_import.api import router
    service, parent, root = published
    monkeypatch.setattr("app.agent_import.api._service", lambda: service)
    monkeypatch.setattr(settings, "agent_import_enabled", True)
    monkeypatch.setattr(settings, "agent_auto_delivery_enabled", False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    fresh = root / "api-source"
    fresh.mkdir()
    (fresh / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\nb\tr2\tANOTHER\tP2\t42\n")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        saved = client.post(f"/api/v1/agent-import-cases/{parent.case_id}/import-recipe", json={"name": "Reusable example"})
        assert saved.status_code == 200, saved.text
        recipe = saved.json()
        assert client.get("/api/v1/import-recipes").json()[0]["display_category"] == "BOTTOM_UP"
        created = client.post(f"/api/v1/import-recipes/{recipe['recipe_id']}/from-path", json={"source_path": str(fresh), "version": recipe["version"]})
        assert created.status_code == 201, created.text
        assert bound_recipe(service, created.json()["case_id"])["recipe_id"] == recipe["recipe_id"]
