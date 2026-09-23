"""Actual configured models on synthetic data; no private source/code egress.

Exercises the real Case research/plan/review methods. It intentionally stops at
the deterministic execution boundary and never calls this a completed delivery.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-configured-models", action="store_true")
    parser.add_argument("--recover-state", type=Path)
    args = parser.parse_args()
    if args.recover_state:
        recover(args.recover_state, args.output)
        return
    if not args.authorize_configured_models:
        raise SystemExit("Explicit model authorization is required")
    root = Path(__file__).resolve().parents[1]
    from dotenv import dotenv_values
    # Copy only model access settings in memory, never dotenv or the database URL.
    configured = dotenv_values(root / "back/.env")
    names = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")
    selected = {key: configured[key] for key in names if configured.get(key)}
    configured.clear()
    if not all(selected.get(key) for key in names):
        raise SystemExit("One OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL connection is required")
    temporary = Path(tempfile.mkdtemp(prefix="viewer-model-probe-"))
    data = temporary / "data"
    source = data / "source"
    source.mkdir(parents=True)
    (source / "unknown-results.tsv").write_text(
        "record\trun\tsequence\tproteins\tintensity\n"
        "one\trun-a\tPEPTIDE\tP1\t0\n"
        "two\trun-b\tANOTHER\tP2\t\n", encoding="utf-8")
    os.environ.update(selected)
    os.environ.update({"VIEWER_ENV": "test", "DATABASE_URL": f"sqlite+pysqlite:///{(temporary / 'cases.sqlite').as_posix()}",
                       "DATA_ROOT": str(data), "AGENT_API_WORKER_ENABLED": "false", "AGENT_INPUT_SNAPSHOT_ENABLED": "true",
                       "AGENT_SOURCE_READ_ENABLED": "false", "AGENT_PUBLIC_DOCUMENTS_JSON": "{}",
                       "AGENT_CASE_DEADLINE_SECONDS": "240", "AGENT_CASE_TOKEN_BUDGET": "300000"})
    sys.path.insert(0, str(root / "back"))
    from app.agent_import.case_service import CaseService
    from app.agent_import.execution_control import ExecutionFence, execution_scope
    from app.agent_import.migrations import ensure_agent_import_schema
    from app.agent_import.workflow import AgentImportWorkflow
    from app.fingerprint import compute_dataset_metadata_fingerprint
    ensure_agent_import_schema()
    service = CaseService()
    case = service.create_case(source_ref=str(source), dataset_fingerprint=compute_dataset_metadata_fingerprint(source).fingerprint,
                               analysis_category="BOTTOM_UP", source_profile="synthetic unknown table",
                               format_details="Synthetic acceptance data only. record identifies the PSM row, run the measurement run, sequence the peptide, proteins the accession. intensity is source intensity. No spectra, FASTA, q-value or decoy facts were supplied. Preserve zero and missing independently; do not create missing facts.")
    claimed = service.claim_next(worker_id="model-probe", lease_seconds=600)
    workflow = AgentImportWorkflow(service=service)
    failure = None
    try:
        with execution_scope(ExecutionFence(case.case_id, claimed.lease_token, lambda amount: service.check_execution(case.case_id, claimed.lease_token, amount))):
            workflow.run_analysis_phase(case.case_id)
            print(json.dumps({"phase": "research_persisted", "case_id": case.case_id}), flush=True)
            candidate = workflow.run_candidate_phase(case.case_id)
            print(json.dumps({"phase": "candidate_returned", "status": candidate.status.value}), flush=True)
            if candidate.status.value == "BUILDING":
                workflow.run_review_phase(case.case_id)
    except Exception as exc:
        failure = str(getattr(exc, "code", type(exc).__name__))
        # Preserve the actual exception category without inventing state success.
    current = service.get_case(case.case_id)
    args.output.mkdir(parents=True, exist_ok=False)
    artifacts = [{"type": item.artifact_type, "sha256": item.sha256, "payload": item.structured_payload} for item in service.list_artifacts(case.case_id)]
    (args.output / "model-artifacts.json").write_text(json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"case_id": case.case_id, "status": current.status.value, "failure_code": failure,
               "model_tokens_reserved": current.model_tokens_reserved, "scope": "real models: research, candidate, review on synthetic TSV only",
               "source_code_sent": False, "private_data_sent": False, "delivery_completed": False}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if failure:
        raise SystemExit(1)


def recover(directory: Path, output: Path) -> None:
    import sqlite3
    directory = directory.resolve(strict=True)
    if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith("viewer-model-probe-"):
        raise SystemExit("Recovery only accepts this harness's isolated temporary directory")
    with sqlite3.connect(f"file:{(directory / 'cases.sqlite').as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT case_id,status,context_revision,model_tokens_reserved FROM agent_import_cases").fetchone()
        artifacts = connection.execute("SELECT artifact_type,sha256,payload_json FROM agent_artifacts ORDER BY created_at").fetchall()
    output.mkdir(parents=True, exist_ok=False)
    summary = {"case_id": row[0], "status": row[1], "context_revision": row[2], "model_tokens_reserved": row[3],
               "interrupted": True, "delivery_completed": False, "recovery_read_only": True,
               "artifact_types": [item[0] for item in artifacts]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "model-artifacts.json").write_text(json.dumps([
        {"type": kind, "sha256": sha, "payload": json.loads(payload) if payload else None} for kind, sha, payload in artifacts
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
