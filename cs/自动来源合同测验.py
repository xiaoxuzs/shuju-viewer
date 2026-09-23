"""Offline registered-source acceptance preparation: no model, API, business DB or Case."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.agent_import.source_acceptance import ensure_registered_acceptance
    from app.agent_import.source_code import canonical_bytes, digest_bytes
    from app.agent_import.input_assets import content_manifest
    from app.agent_import.verification import load_acceptance_contract
    from app.agent_import.verification_full import ReconciliationLedger, populate_source
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest = content_manifest(args.source)
    requirements = digest_bytes(canonical_bytes({"analysis_category": "AUTO", "source_profile": "Unknown format", "format_details": None, "user_messages": []}))
    binding = ensure_registered_acceptance(args.source, source_identity=manifest["sha256"], requirements_sha256=requirements, oracle_root=args.output / "contracts")
    contract = load_acceptance_contract((args.output / "contracts" / f"{manifest['sha256']}-{requirements}.json").read_text(encoding="utf-8"))
    ledger = ReconciliationLedger(args.output / "expectations.sqlite", contract)
    try:
        report = populate_source(ledger, args.source)
        report["protein_groups"] = ledger.db.execute("SELECT count(*) FROM expected_groups").fetchone()[0]
        report["fasta_accession_keys"] = ledger.db.execute("SELECT count(*) FROM expected_sequences").fetchone()[0]
    finally:
        ledger.close()
    report.update(binding=binding, elapsed_seconds=time.monotonic() - started, real_model_calls=0,
        scope="registered independent source rule and complete expected-source ledger only; NOT a model/import success")
    (args.output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
