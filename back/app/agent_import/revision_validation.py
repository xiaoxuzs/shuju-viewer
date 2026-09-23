"""Trusted source-to-namespace reconciliation; never callable by generated code.

This produces only projection evidence. Application/HTTP/browser evidence is a
separate mandatory input to RevisionStore.seal; this function cannot publish.
"""
import hashlib
import hmac
import json
from pathlib import Path

from sqlalchemy import text

from .input_assets import content_manifest, hash_file
from .source_code import canonical_bytes
from .verification_full import ReconciliationLedger, populate_source, reconcile_semantic, FullVerificationError
from .verification_full_stage import projection_records, check_projected_intensity


def verify_revision_projection(store, revision, *, contract, input_root, ledger_path):
    from app.declarative_ingest import read_semantic_zp
    row = store._row(revision)
    if row["state"] != "PREPARING" or row["source_sha256"] != contract.source_identity or row["build_sha256"] != store.build:
        raise FullVerificationError("REVISION_CONTRACT_IDENTITY_MISMATCH")
    candidate = Path(row["zp_path"])
    if hash_file(candidate) != row["zp_sha256"]:
        raise FullVerificationError("REVISION_CANDIDATE_CHANGED")
    ledger = ReconciliationLedger(Path(ledger_path), contract)
    before = store.projection_digest(revision)
    try:
        coverage = {"source": populate_source(ledger, Path(input_root))}
        semantic = read_semantic_zp(candidate)
        coverage["semantic"] = reconcile_semantic(ledger, semantic)
        with store.projection(revision) as db:
            identity = db.execute(text("SELECT dataset_id,slug FROM datasets")).all()
            if identity != [(row["dataset_id"], row["slug"])]:
                raise FullVerificationError("REVISION_DATASET_IDENTITY_MISMATCH")
            for _, record, api in projection_records(db, row["dataset_id"], contract.batch_size):
                ledger.check()
                ledger.compare("projection", record)
                check_projected_intensity(ledger, record, api)
            coverage["projection"] = ledger.finish("projection")
            for kind, sql in (
                ("peptide", "SELECT sequence FROM peptides WHERE dataset_id=:id"),
                ("protein", "SELECT accession FROM proteins WHERE dataset_id=:id"),
            ):
                expected = {r[0] for r in ledger.db.execute("SELECT k FROM source_entities WHERE kind=?", (kind,))}
                actual = db.execute(text(sql), {"id": row["dataset_id"]}).scalars().all()
                if len(actual) != len(expected) or set(actual) != expected:
                    raise FullVerificationError("REVISION_ENTITY_SCOPE_MISMATCH")
            expected_runs = {r[0] for r in ledger.db.execute("SELECT k FROM source_entities WHERE kind='run'")}
            actual_runs = []
            for metadata in db.execute(text("SELECT run_metadata FROM runs WHERE dataset_id=:id"), {"id": row["dataset_id"]}).scalars():
                actual_runs.append((json.loads(metadata) if isinstance(metadata, str) else metadata)["run_name"])
            if len(actual_runs) != len(expected_runs) or set(actual_runs) != expected_runs:
                raise FullVerificationError("REVISION_RUN_SCOPE_MISMATCH")
            for peptide, protein in db.execute(text("""SELECT p.sequence,pr.accession FROM protein_relation_mapping rm
                LEFT JOIN peptides p ON p.dataset_id=rm.dataset_id AND p.peptide_id=rm.entity_id
                LEFT JOIN proteins pr ON pr.dataset_id=rm.dataset_id AND pr.protein_id=rm.protein_id
                WHERE rm.dataset_id=:id AND rm.entity_type='PEPTIDE'"""), {"id": row["dataset_id"]}):
                if ledger.db.execute("DELETE FROM source_edges WHERE peptide=? AND protein=?", (peptide, protein)).rowcount != 1:
                    raise FullVerificationError("REVISION_RELATION_MISMATCH")
            if ledger.db.execute("SELECT count(*) FROM source_edges").fetchone()[0]:
                raise FullVerificationError("REVISION_RELATION_MISSING")
            assets = db.execute(text("SELECT zp_path,output_sha256 FROM dataset_zp_assets WHERE dataset_id=:id AND status='active'"), {"id": row["dataset_id"]}).all()
            if assets != [(row["zp_path"], row["zp_sha256"])]:
                raise FullVerificationError("REVISION_ASSET_MISMATCH")
        if store.projection_digest(revision) != before or hash_file(candidate) != row["zp_sha256"] or content_manifest(Path(input_root))["sha256"] != contract.source_identity:
            raise FullVerificationError("REVISION_INPUT_CHANGED_DURING_CHECK")
        record = {"revision_id": revision, "dataset_id": row["dataset_id"], "projection_sha256": before,
            "zp_sha256": row["zp_sha256"], "source_sha256": row["source_sha256"], "build_sha256": store.build,
            "environment_sha256": row["environment_sha256"], "status": "PASSED"}
        return {"record": record, "signature": hmac.new(store.key, canonical_bytes(record), hashlib.sha256).hexdigest(),
                "coverage": coverage, "scope": "source/semantic/namespace entities and relations; HTTP/browser/activation NOT asserted"}
    finally:
        ledger.close()
