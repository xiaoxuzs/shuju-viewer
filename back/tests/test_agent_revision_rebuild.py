"""Actual Writer/SQL projection rebuild; no model/browser/publication claims."""
import pytest
from sqlalchemy import text

from test_agent_zp_import import isolated_agent_zp_settings  # existing isolated universal-schema fixture
from test_semantic_zp_projection import _plan
from app.core.config import settings
from app.core.db import engine, SessionLocal
from app.declarative_ingest import build_declarative_zp_artifact
from app.agent_zp.service import import_agent_zp_candidate
from app.schemas.agent_zp import AgentZpImportCreateIn
from app.agent_import.revisions import RevisionStore
from app.agent_import.revision_validation import verify_revision_projection
from app.agent_import.input_assets import content_manifest
from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation, FullVerificationError


def test_new_zp_rebuild_preserves_logical_identity_and_independent_receipt(tmp_path):
    root = settings.resolved_data_root
    original = root / "original"
    replacement = root / "replacement"
    original.mkdir()
    replacement.mkdir()
    header = "id\trun\tsequence\tproteins\tintensity\n"
    (original / "results.tsv").write_text(header + "a\tr1\tPEPTIDE\tP1\t0\n")
    (replacement / "results.tsv").write_text(header + "a\tr1\tPEPTIDE\tP1\t42\nb\tr2\tANOTHER\tP2\t\n")
    first = build_declarative_zp_artifact(source_root=original, source_fingerprint="a"*32, plan=_plan(with_fasta=False), output_path=root / "original.zp")
    new = build_declarative_zp_artifact(source_root=replacement, source_fingerprint="a"*32, plan=_plan(with_fasta=False), output_path=root / "replacement.zp")
    with SessionLocal() as db:
        imported = import_agent_zp_candidate(db, AgentZpImportCreateIn(source_path=str(first.path), slug="revision-rebuild", name="Rebuild fixture",
            analysis_category="BOTTOM_UP", source_profile="synthetic", binary_operation="register_existing_zp"), source_fingerprint="a"*32)
    store = RevisionStore(engine, tmp_path / "revisions", build_sha256="b"*64, signing_key=b"synthetic-projection-test-key-only-00")
    store.ensure_schema()
    source_sha = content_manifest(replacement)["sha256"]
    revision = store.prepare_from_zp(imported.dataset_id, imported.dataset_slug, source_sha256=source_sha, zp_path=new.path, environment_sha256="c"*64)
    with SessionLocal() as db:
        assert db.execute(text("SELECT intensity FROM identification_matches WHERE dataset_id=:id"), {"id": imported.dataset_id}).scalars().all() == [0]
        assert db.execute(text("SELECT count(*) FROM datasets")).scalar() == 1
    with store.projection(revision) as db:
        values = db.execute(text("SELECT p.sequence,im.intensity FROM identification_matches im JOIN peptides p ON p.peptide_id=im.entity_id AND p.dataset_id=im.dataset_id")).all()
        assert dict(values) == {"PEPTIDE": 42, "ANOTHER": None}
        assert db.execute(text("SELECT dataset_id,source_dataset_fingerprint FROM datasets")).one() == (imported.dataset_id, "a"*32)
    contract = FullAcceptanceContract(source_identity=source_sha, source_evidence="Independent source fixture: two rows in two runs; 42 and missing identification intensity.",
        scope="complete replacement synthetic table", source_roles={"results.tsv": "identifications"},
        table=TableExpectation(relative_path="results.tsv", reader="delimited", id_column="id", run_column="run", sequence_column="sequence",
            proteins_column="proteins", quantity_column="intensity", quantity_unit="source_intensity", semantics_evidence="Synthetic identification-level quantity with explicit fixture unit; no channel/sample."))
    receipt = verify_revision_projection(store, revision, contract=contract, input_root=replacement, ledger_path=tmp_path / "independent.sqlite")
    assert receipt["record"]["projection_sha256"] == store.projection_digest(revision)
    assert receipt["coverage"]["projection"]["expected"] == 2
    assert store._row(revision)["state"] == "PREPARING"  # no fake application receipt or activation
    with store.projection(revision, writable=True) as db:
        db.execute(text("UPDATE identification_matches SET intensity=17 WHERE intensity=42"))
    with pytest.raises(FullVerificationError):
        verify_revision_projection(store, revision, contract=contract, input_root=replacement, ledger_path=tmp_path / "negative.sqlite")


def test_revision_reconciliation_includes_extended_source_contract_fields(tmp_path):
    from app.declarative_ingest import DeclarativeImportPlan
    root = settings.resolved_data_root
    source = root / "extended"
    source.mkdir()
    (source / "results.tsv").write_text("id\trun\tsequence\tproteins\tintensity\tpep\tmass\tscan\na\tr1\tPEPTIDE\tP1\t0\t0.03\t897.5\t\n")
    payload = _plan(with_fasta=False).model_dump(mode="json")
    payload["sources"][0]["required_fields"].extend(["pep", "mass", "scan"])
    for field, target, kind in [("pep", "pep", "float"), ("mass", "neutral_mass", "float"), ("scan", "scan_number", "integer")]:
        payload["field_mappings"].append({"mapping_id": "map-" + field, "source_id": "ids", "source_field": field,
            "target_entity": "identification", "target_field": target, "value_kind": kind, "evidence_refs": ["source"]})
    candidate = build_declarative_zp_artifact(source_root=source, source_fingerprint="a" * 32,
        plan=DeclarativeImportPlan.model_validate(payload), output_path=root / "extended.zp")
    with SessionLocal() as db:
        imported = import_agent_zp_candidate(db, AgentZpImportCreateIn(source_path=str(candidate.path), slug="extended-revision", name="Extended fields",
            analysis_category="BOTTOM_UP", source_profile="synthetic", binary_operation="register_existing_zp"), source_fingerprint="a" * 32)
    store = RevisionStore(engine, tmp_path / "namespaces", build_sha256="b" * 64, signing_key=b"synthetic-extended-projection-test-key")
    store.ensure_schema()
    source_sha = content_manifest(source)["sha256"]
    revision = store.prepare_from_zp(imported.dataset_id, imported.dataset_slug, source_sha256=source_sha, zp_path=candidate.path, environment_sha256="c" * 64)
    contract = FullAcceptanceContract(schema_version=3, verifier_version="full-semantic-v2.1", source_identity=source_sha, source_evidence="Independent synthetic extended table",
        scope="one row with PEP, neutral mass and missing scan", source_roles={"results.tsv": "identifications"},
        table=TableExpectation(relative_path="results.tsv", reader="delimited", id_column="id", run_column="run", sequence_column="sequence",
            proteins_column="proteins", quantity_column="intensity", quantity_unit="source_intensity", pep_column="pep", neutral_mass_column="mass", scan_column="scan",
            semantics_evidence="Synthetic explicit identification fields; absent scan preserved, no inferred spectrum link."))
    receipt = verify_revision_projection(store, revision, contract=contract, input_root=source, ledger_path=tmp_path / "extended-check.sqlite")
    assert receipt["coverage"]["projection"]["errors"] == 0
    with store.projection(revision, writable=True) as db:
        db.execute(text("UPDATE identification_matches SET pep=0.5"))
    with pytest.raises(FullVerificationError):
        verify_revision_projection(store, revision, contract=contract, input_root=source, ledger_path=tmp_path / "extended-negative.sqlite")
