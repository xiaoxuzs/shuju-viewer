"""Trusted fixed DIACLIP mapping to debug full validation before any paid model calls.

Not the normal-entry/model acceptance. All input files/records are retained.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browser-cache", type=Path)
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--verify-existing", type=Path, help="Own prior fixed-summary.json; runs fresh validation, never counts as model acceptance")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--freeze-code", action="store_true", help="Validate an immutable current-workspace snapshot, allowing unrelated development to continue")
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    temporary = Path(tempfile.mkdtemp(prefix="viewer-full-fixed-"))
    data = temporary / "data"
    data.mkdir()
    os.environ.update({"VIEWER_ENV": "test", "DATABASE_URL": f"sqlite+pysqlite:///{(temporary / 'unused.sqlite').as_posix()}", "DATA_ROOT": str(data), "AGENT_API_WORKER_ENABLED": "false"})
    for name in ("OPENAI_API_KEY",):
        os.environ.pop(name, None)
    sys.path.insert(0, str(root / "back"))
    from app.agent_import.input_assets import freeze_source
    from app.agent_import.research_tools import AgentResearchToolbox
    from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation, ReconciliationLedger, populate_source, reconcile_semantic
    from app.agent_import.verification_metrics import peak_rss_bytes
    from app.agent_import.verification import CandidateVerifier, VerificationRuntime
    from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact
    from app.fingerprint import compute_dataset_metadata_fingerprint
    if args.verify_existing:
        previous = json.loads(args.verify_existing.read_text(encoding="utf-8"))
        contract = FullAcceptanceContract.model_validate_json(args.verify_existing.with_name("oracle.json").read_text(encoding="utf-8"))
        if args.core_only:
            from app.agent_import.verification_full_stage import check_spectra
            started = time.monotonic()
            report = check_spectra(args.candidate or Path(previous["candidate"]), args.input_root or Path(previous["input_root"]), contract, lambda: None)
            args.output.mkdir(parents=True, exist_ok=False)
            report.update(elapsed_seconds=time.monotonic()-started, peak_rss_bytes=peak_rss_bytes())
            (args.output / "core.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report), flush=True)
            return
        validation_root = root
        if args.freeze_code:
            from app.agent_import.source_code import SourceSnapshot
            import subprocess
            validation_root = args.output.resolve() / "validated-code"
            SourceSnapshot.capture(root).export(validation_root)
            subprocess.run([str(args.node), "-e", "require('fs').symlinkSync(process.argv[1],process.argv[2],'junction')",
                str(root / "front/node_modules"), str(validation_root / "front/node_modules")], check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        runtime = VerificationRuntime(validation_root, args.postgres_bin, Path(sys.executable), args.node, args.browser_cache, args.output.resolve())
        receipt = CandidateVerifier(runtime, signing_key=secrets.token_bytes(32)).verify(args.candidate or Path(previous["candidate"]), contract,
            case_id="fixed-real-diaclip", input_root=args.input_root or Path(previous["input_root"]))
        print(json.dumps({"status": receipt["record"]["status"], "operation": receipt["record"]["operation_key"], "model_invoked": False}), flush=True)
        return
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    retained = freeze_source(source, data / "retained")
    frozen = data / "retained/files"
    tables = list(frozen.glob("*.diaclip.fdr.parquet"))
    mzml = list(frozen.glob("*.mzML"))
    if len(tables) != 1 or len(mzml) != 1:
        raise ValueError("This fixed diagnostic requires the complete registered one-table/one-mzML bundle")
    observation = AgentResearchToolbox(frozen).execute("inspect_source_file", {"relative_path": tables[0].name})
    if observation["facts"].get("profile") != "diaclip-fdr-reader-v1":
        raise ValueError("The registered Reader did not establish the expected source contract")
    contract = FullAcceptanceContract(source_identity=retained["sha256"], source_evidence="Existing complete DIA-CLIP FDR bundle; registered Reader declares DIA and RT minutes. Independent PyArrow source oracle preserves all reported rows including decoys; no FDR/search is rerun.",
        scope="Every supplied identification row, original field, group membership and complete companion mzML; no invented PSM-to-spectrum relation",
        table=TableExpectation(relative_path=tables[0].name, reader="parquet", identity="source_row", run_column="Run", sequence_column="Stripped.Sequence",
            modified_column="Modified.Sequence", rt_column="RT", rt_unit="minute", q_column="DIAClip.Q.Value", score_column="DIAClip.Score",
            charge_column="Precursor.Charge", mz_column="Precursor.Mz", decoy_column="Decoy", proteins_column="Protein.Ids",
            group_column="Protein.Group", group_members_column="Protein.Group", quantity_column="DIAClip.Quantity", quantity_unit="source_intensity",
            semantics_evidence=observation["facts"]["semantics_evidence"]),
        source_roles={tables[0].name: "identifications", mzml[0].name: "spectra"}, numeric_absolute_tolerance=1e-7,
        required_views={"bu.matches": "AVAILABLE", "bu.peptides": "AVAILABLE", "bu.proteins": "PARTIAL", "quantification": "AVAILABLE"})
    (output / "oracle.json").write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    rows = [
        ("Run", "run", "name", "string", "identity", None, True),
        ("Stripped.Sequence", "peptide", "sequence", "string", "identity", None, True),
        ("Modified.Sequence", "identification", "modified_sequence", "string", "identity", None, True),
        ("Precursor.Charge", "identification", "charge", "integer", "identity", None, True),
        ("Precursor.Mz", "identification", "precursor_mz", "float", "identity", None, True),
        ("RT", "identification", "rt_seconds", "float", "minute_to_second", "minute", True),
        ("DIAClip.Q.Value", "identification", "q_value", "float", "identity", None, True),
        ("DIAClip.Score", "identification", "score", "float", "identity", None, True),
        ("Decoy", "identification", "is_decoy", "boolean", "identity", None, True),
        ("Protein.Ids", "identification", "protein_accessions", "string", "semicolon_split", None, True),
        ("Protein.Group", "identification", "protein_group_ids", "string", "singleton_list", None, False),
        ("Protein.Group", "protein_group", "source_id", "string", "identity", None, False),
        ("Protein.Group", "protein_group", "member_accessions", "string", "semicolon_split", None, False),
        ("DIAClip.Quantity", "quantification", "value", "float", "identity", "source_intensity", True),
    ]
    fields = [f["name"] for f in observation["facts"]["fields"]]
    plan = DeclarativeImportPlan.model_validate({"schema_version": 1, "plan_id": "trusted-diaclip-full-diagnostic", "analysis_mode": "BOTTOM_UP",
        "sources": [{"source_id": "table", "relative_path": tables[0].name, "role": "identification_table", "reader": "parquet", "identification_identity": "source_row", "required_fields": fields},
                    {"source_id": "spectra", "relative_path": mzml[0].name, "role": "spectrum_source", "reader": "mzml"}],
        "acquisition_mode": "dia", "acquisition_mode_evidence_refs": ["registered-source"],
        "field_mappings": [{"mapping_id": f"m-{i}", "source_id": "table", "source_field": field, "target_entity": entity, "target_field": target,
                            "value_kind": kind, "transform": transform, "unit": unit, "required": required, "evidence_refs": ["registered-source"]}
                            for i, (field, entity, target, kind, transform, unit, required) in enumerate(rows)],
        "unmapped_fields": {"table": sorted(set(fields) - {r[0] for r in rows})},
        "requested_views": [{"view_id": view} for view in contract.required_views]})
    (output / "fixed-plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"phase": "frozen_source", "files": len(retained["files"]), "bytes": sum(v["size"] for v in retained["files"].values()), "rows": observation["facts"]["rows_scanned"], "model_invoked": False}), flush=True)
    artifact = build_declarative_zp_artifact(source_root=frozen, source_fingerprint=compute_dataset_metadata_fingerprint(source).fingerprint,
        plan=plan, output_path=data / "full.zp")
    print(json.dumps({"phase": "zp_generated", "seconds": time.monotonic() - started, "bytes": artifact.path.stat().st_size, "peak_rss_bytes": peak_rss_bytes()}), flush=True)
    ledger = ReconciliationLedger(output / "source-semantic.sqlite", contract)
    try:
        source_report = populate_source(ledger, frozen)
        semantic_report = reconcile_semantic(ledger, artifact.semantic_dataset)
    finally:
        ledger.close()
    (output / "fixed-summary.json").write_text(json.dumps({"candidate": str(artifact.path), "input_root": str(frozen), "source": source_report,
        "semantic": semantic_report, "peak_rss_bytes": peak_rss_bytes(), "elapsed_seconds": time.monotonic() - started, "model_invoked": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.candidate_only:
        runtime = VerificationRuntime(root, args.postgres_bin, Path(sys.executable), args.node, args.browser_cache, output)
        receipt = CandidateVerifier(runtime, signing_key=secrets.token_bytes(32)).verify(artifact.path, contract, case_id="fixed-real-diaclip", input_root=frozen)
        print(json.dumps({"status": receipt["record"]["status"], "scope": contract.scope, "model_invoked": False}), flush=True)


if __name__ == "__main__":
    main()
