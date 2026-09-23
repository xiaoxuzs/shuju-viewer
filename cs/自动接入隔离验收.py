"""Explicit local acceptance; owns a NEW cluster and never reads project dotenv.

This run uses synthetic source oracles and the real Writer/PostgreSQL/HTTP/browser.
It is not a live-model test, nor a production deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--browser-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-format", choices=("tsv", "jsonl"), default="tsv")
    parser.add_argument("--gpt-diagnostic-artifact", type=Path, help="Retained real-model plan+review on the exact two-row diagnostic fixture; not a normal-entry model delivery")
    parser.add_argument("--full-oracle", action="store_true", help="Run the same independent small fixture through v2 full-scope reconciliation")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    temporary = Path(tempfile.mkdtemp(prefix="viewer-oracle-"))
    data = temporary / "data"
    data.mkdir()
    os.environ.update({"VIEWER_ENV": "test", "DATABASE_URL": f"sqlite+pysqlite:///{(temporary / 'unused.sqlite').as_posix()}",
                       "DATA_ROOT": str(data), "AGENT_API_WORKER_ENABLED": "false"})
    for name in ("OPENAI_API_KEY",):
        os.environ.pop(name, None)
    sys.path.insert(0, str(root / "back"))
    from app.agent_import.input_assets import content_manifest, freeze_source
    from app.agent_import.verification import AcceptanceContract, CandidateVerifier, VerificationRuntime
    from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact
    from app.fingerprint import compute_dataset_metadata_fingerprint

    source = data / "source"
    source.mkdir()
    (source / "measurements.tsv").write_text(
        "record\trun\tsequence\tproteins\trt\tamount\n"
        "one\trun-a\tPEPTIDE\tP1\t60\t0\n"
        "two\trun-b\tANOTHER\tP2\t120\t\n", encoding="utf-8",
    )
    source_name = "measurements.tsv"
    reader = {"reader": "delimited", "delimiter": "\t"}
    physical = {key: key for key in ("record", "run", "sequence", "proteins", "rt", "amount")}
    expected_rows = [
        {"source_record_id": "one", "sequence": "PEPTIDE", "rt_minutes": 1.0, "quantification_values": [0.0], "quantification_units": ["source_intensity"]},
        {"source_record_id": "two", "sequence": "ANOTHER", "rt_minutes": 2.0, "quantification_values": [None], "quantification_units": ["source_intensity"]},
    ]
    if args.source_format == "jsonl":
        (source / "measurements.tsv").unlink()  # this harness's freshly created synthetic fixture only
        source_name = "different-layout.ndjson"
        reader = {"reader": "jsonl"}
        physical = {"record": "event_id", "run": "sample_run", "sequence": "peptide_sequence", "proteins": "accession", "rt": "retention_seconds", "amount": "abundance"}
        (source / source_name).write_text(
            json.dumps({"abundance": 17.5, "accession": "Q9", "event_id": "alpha", "retention_seconds": 90, "peptide_sequence": "PEPTIDER", "sample_run": "sample-x"}) + "\n" +
            json.dumps({"sample_run": "sample-y", "peptide_sequence": "ANOTHERK", "event_id": "beta", "accession": "Q8", "abundance": None, "retention_seconds": 0}) + "\n", encoding="utf-8")
        expected_rows = [
            {"source_record_id": "alpha", "sequence": "PEPTIDER", "rt_minutes": 1.5, "quantification_values": [17.5], "quantification_units": ["source_intensity"]},
            {"source_record_id": "beta", "sequence": "ANOTHERK", "rt_minutes": 0.0, "quantification_values": [None], "quantification_units": ["source_intensity"]},
        ]
    source_identity = content_manifest(source)["sha256"]
    frozen = data / "retained"
    freeze_source(source, frozen)
    mapping = [("record", "identification", "source_id", "string", "identity", None),
               ("run", "run", "name", "string", "identity", None),
               ("sequence", "peptide", "sequence", "string", "identity", None),
               ("proteins", "identification", "protein_accessions", "string", "semicolon_split", None),
               ("rt", "identification", "rt_seconds", "float", "identity", "second"),
               ("amount", "quantification", "value", "float", "identity", "source_intensity")]
    plan = DeclarativeImportPlan.model_validate({
        "schema_version": 1, "plan_id": "independent-source-oracle-v1", "analysis_mode": "BOTTOM_UP",
        "sources": [{"source_id": "table", "relative_path": source_name, "role": "identification_table",
                     **reader, "required_fields": [physical[entry[0]] for entry in mapping]}],
        "field_mappings": [{"mapping_id": f"field-{field}", "source_id": "table", "source_field": physical[field],
                            "target_entity": entity, "target_field": target, "value_kind": kind,
                            "transform": transform, "unit": unit, "required": field != "amount",
                            "evidence_refs": ["trusted-fixture-spec:v1"]}
                           for field, entity, target, kind, transform, unit in mapping],
        "unmapped_fields": {"table": []},
        "requested_views": [{"view_id": "bu.matches"}, {"view_id": "quantification"}],
    })
    if args.gpt_diagnostic_artifact:
        from app.agent_import.contracts import AgentCandidatePlan, AgentPlanReview
        phases = json.loads(args.gpt_diagnostic_artifact.read_text(encoding="utf-8"))
        candidate_phase = next(p for p in phases if p["phase"] == "B_D_gpt_frozen_synthetic_plan")
        review_phase = next(p for p in phases if p["phase"] == "D_gpt_review")
        if not candidate_phase["passed"] or not review_phase["passed"] or AgentPlanReview.model_validate(review_phase["result"]).status != "APPROVED":
            raise ValueError("A genuinely retained approved diagnostic plan is required")
        candidate = AgentCandidatePlan.model_validate(candidate_phase["result"])
        if candidate.status != "READY" or candidate.zp_conversion_plan is None or candidate.zp_conversion_plan.declarative_plan is None:
            raise ValueError("Expected an executable declarative model plan")
        plan = candidate.zp_conversion_plan.declarative_plan
        # Recreate only the exact public synthetic diagnostic fixture. No private data is selected.
        (source / source_name).unlink()
        (source / "unknown-results.tsv").write_text("record\trun\tsequence\tproteins\tintensity\none\trun-a\tPEPTIDE\tP1\t0\ntwo\trun-b\tANOTHER\tP2\t\n", encoding="utf-8")
        source_identity = content_manifest(source)["sha256"]
        frozen = data / "retained-model-input"
        freeze_source(source, frozen)
        expected_rows = [
            {"source_record_id": "one", "sequence": "PEPTIDE", "rt_minutes": None, "quantification_values": [0.0], "quantification_units": [None]},
            {"source_record_id": "two", "sequence": "ANOTHER", "rt_minutes": None, "quantification_values": [None], "quantification_units": [None]},
        ]
    artifact = build_declarative_zp_artifact(source_root=frozen / "files",
        source_fingerprint=compute_dataset_metadata_fingerprint(source).fingerprint,
        plan=plan, output_path=data / "candidate.zp")
    # Explicit independent scientific oracle, not values computed by the mapper/API.
    oracle = AcceptanceContract(source_identity=source_identity,
        source_evidence=("Synthetic TSV: one=60 seconds/zero intensity; two=120 seconds/missing intensity." if args.source_format == "tsv" else "Independent synthetic JSONL: alpha=90 seconds/17.5 intensity; beta=0 seconds/missing intensity. Renamed and reordered fields.") + " No q-value, decoy, FASTA or spectra supplied.",
        total_matches=2, scope=f"all 2 synthetic {args.source_format} identification rows across 2 table-only runs",
        matches=expected_rows)
    if args.gpt_diagnostic_artifact:
        oracle = oracle.model_copy(update={"source_evidence": "Independent exact synthetic diagnostic source: two records one/PEPTIDE/intensity zero and two/ANOTHER/missing intensity. No RT, unit, q-value, decoy or spectra were supplied. Mapping was produced by the real GPT service; expected values are from the source specification, not that mapping.",
                                           "scope": "all two synthetic diagnostic rows; retained GPT plan; not normal-entry live-model delivery"})
    if args.full_oracle:
        if args.gpt_diagnostic_artifact:
            raise ValueError("The overlap run uses its independent fixed fixture, not a retained model plan")
        from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation
        oracle = FullAcceptanceContract(source_identity=source_identity, source_evidence=oracle.source_evidence,
            scope=oracle.scope, table=TableExpectation(relative_path=source_name, reader=reader["reader"],
                id_column=physical["record"], run_column=physical["run"], sequence_column=physical["sequence"], proteins_column=physical["proteins"],
                rt_column=physical["rt"], rt_unit="second", quantity_column=physical["amount"], quantity_unit="source_intensity",
                semantics_evidence="Independent fixture specification: retention seconds and identification source intensity, null distinct from zero."),
            source_roles={source_name: "identifications"})
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "oracle.json").write_text(oracle.model_dump_json(indent=2), encoding="utf-8")
    runtime = VerificationRuntime(source_root=root, postgres_bin=args.postgres_bin.resolve(), python=Path(sys.executable),
                                  node=args.node.resolve(), browser_cache=args.browser_cache.resolve(), evidence_root=args.output)
    receipt = CandidateVerifier(runtime, signing_key=secrets.token_bytes(32)).verify(artifact.path, oracle, case_id="synthetic-real-stack", input_root=frozen / "files")
    print(json.dumps({"status": receipt["record"]["status"], "operation_key": receipt["record"]["operation_key"],
                      "scope": receipt["record"]["scope"], "evidence": str(args.output),
                      "candidate": str(artifact.path), "model_invoked": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
