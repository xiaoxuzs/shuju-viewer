"""Fixed synthetic PG test: build two new ZP-backed namespaces, never activate."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("VIEWER_ENV") != "test" or not os.environ.get("VIEWER_BUILD_ID"):
        raise SystemExit("Only identified synthetic local test runtimes")
    sys.path.insert(0, str(Path.cwd()))
    from sqlalchemy import text
    from app.core.config import settings
    from app.core.db import engine
    from app.agent_import.case_service import CaseService
    from app.agent_import.revisions import RevisionStore
    from app.agent_import.revision_validation import verify_revision_projection
    from app.agent_import.input_assets import content_manifest
    from app.agent_import.source_code import canonical_bytes
    from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation
    from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact
    case = CaseService().get_case(args.case)
    expected = "record\trun\tsequence\tproteins\tintensity\none\trun-a\tPEPTIDE\tP1\t0\ntwo\trun-b\tANOTHER\tP2\t\n"
    if case.status.value != "SUCCESS" or case.source_profile not in {"synthetic-gpt-normal-entry", "Unknown format"} or (Path(case.source_ref) / "unknown-results.tsv").read_text() != expected:
        raise SystemExit("This test cannot modify real scientific data")
    root = settings.resolved_data_root / "revision-fixture"
    root.mkdir()
    source = root / "source"
    source.mkdir()
    (source / "unknown-results.tsv").write_text(expected.replace("P1\t0", "P1\t42"))
    spec = importlib.util.spec_from_file_location("transport_fixture", Path(__file__).with_name("智能导入传输夹具.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = DeclarativeImportPlan.model_validate(module.candidate()["zp_conversion_plan"]["declarative_plan"])
    artifact = build_declarative_zp_artifact(source_root=source, source_fingerprint=case.dataset_fingerprint, plan=plan, output_path=root / "new.zp")
    store = RevisionStore(engine, root / "namespaces", build_sha256=settings.viewer_build_id,
                          signing_key=settings.agent_verification_signing_key.encode())
    with engine.connect() as db:
        pg_version = db.execute(text("SHOW server_version")).scalar_one()
    environment = {"python": sys.version, "postgres": pg_version, "environment": "test",
        "packages": {name: importlib.metadata.version(name) for name in ("sqlalchemy", "psycopg", "pydantic")},
        "lock_sha256": hashlib.sha256((Path.cwd() / "uv.lock").read_bytes()).hexdigest()}
    environment_sha = hashlib.sha256(canonical_bytes(environment)).hexdigest()
    first = store.prepare_from_zp(case.dataset_id, case.dataset_slug, source_sha256=content_manifest(Path(case.source_ref))["sha256"],
        zp_path=Path(case.candidate_zp_path), environment_sha256=environment_sha)
    second = store.prepare_from_zp(case.dataset_id, case.dataset_slug, source_sha256=content_manifest(source)["sha256"],
        zp_path=artifact.path, environment_sha256=environment_sha)
    receipts = []
    for revision, input_root in ((first, Path(case.source_ref)), (second, source)):
        contract = FullAcceptanceContract(source_identity=content_manifest(input_root)["sha256"],
            source_evidence="Independent synthetic specification: two runs, first quantity 0 in original or 42 in replacement, second missing; units unknown.",
            scope="all two fixture records, runs, proteins and relations", source_roles={"unknown-results.tsv": "identifications"},
            table=TableExpectation(relative_path="unknown-results.tsv", reader="delimited", id_column="record", run_column="run", sequence_column="sequence",
                proteins_column="proteins", quantity_column="intensity", semantics_evidence="Identification quantity; unknown unit, no channel/sample; all rows retained."))
        receipt = verify_revision_projection(store, revision, contract=contract, input_root=input_root, ledger_path=root / (revision + ".sqlite"))
        receipts.append(receipt)
    assert receipts[0]["record"]["projection_sha256"] != receipts[1]["record"]["projection_sha256"]
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM datasets")).scalar() == 1
        assert db.execute(text("SELECT active_revision_id FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": case.dataset_id}).scalar() == "legacy"
    args.output.write_text(json.dumps({"passed": True, "scope": "real PG new-ZP rebuild and independent namespace reconciliation; no HTTP revision activation or rollback claimed",
        "dataset_id": case.dataset_id, "original_case": case.case_id, "environment": environment, "receipts": receipts}, indent=2), encoding="utf-8")
    engine.dispose()


if __name__ == "__main__":
    main()
