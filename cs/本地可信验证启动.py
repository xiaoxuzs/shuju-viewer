"""Local existing workspace API + independent Worker, with protected MaxQuant acceptance.

This is NOT an auto-test grant or a generated-code runner. It never retries a Case,
changes a model plan, imports a dataset, or modifies .env. Publication stays on
the existing reviewed-import route. Validation owns a separate temporary PG.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "back"))


def prepare(args):
    from app.agent_import.case_service import get_case_service
    from app.agent_import.input_assets import content_manifest
    from app.agent_import.test_storage import protect_secrets
    from app.agent_import.verification_full import FullAcceptanceContract, ReconciliationLedger, populate_source
    from app.source_inspection.registered import _maxquant_table_contract, _thermo_dependent_filter_contract
    case = get_case_service().get_case(args.case)
    snapshot = (case.strategy_payload or {}).get("input_snapshot")
    if not snapshot or not case.strategy_payload.get("requirements_sha256"):
        raise RuntimeError("This Case needs retained research/source identity first")
    from app.core.config import settings
    source = settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source" / "files"
    manifest = content_manifest(source)
    if manifest["sha256"] != snapshot["sha256"]:
        raise RuntimeError("Retained source identity changed")
    from app.agent_import.source_acceptance import build_registered_acceptance
    contract = build_registered_acceptance(source, source_identity=manifest["sha256"],
        requirements_sha256=case.strategy_payload["requirements_sha256"])
    args.runtime.mkdir(parents=True, exist_ok=False)
    oracles = args.runtime / "protected-oracles"
    oracles.mkdir()
    oracle_file = oracles / f"{manifest['sha256']}-{contract.requirements_sha256}.json"
    oracle_file.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    ledger = ReconciliationLedger(args.runtime / "independent-source.sqlite", contract)
    try:
        report = populate_source(ledger, source)
        report["protein_groups"] = ledger.db.execute("SELECT count(*) FROM expected_groups").fetchone()[0]
    finally:
        ledger.close()
    (args.runtime / "source-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.runtime / "validation-key.dpapi").write_bytes(protect_secrets({"signing_key": secrets.token_urlsafe(48)}))
    config = {"case_id": case.case_id, "postgres_bin": str(args.postgres_bin.resolve()), "node": str(args.node.resolve()),
        "browser_cache": str(args.browser_cache.resolve()), "port": args.port, "source_identity": manifest["sha256"],
        "scope": contract.scope, "api_database": "existing user-started local workspace; verifier uses a separate new temporary cluster"}
    (args.runtime / "runtime-public.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def start(args):
    from app.core.config import settings
    from app.agent_import.test_storage import unprotect_secrets
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Only the already configured local workspace is permitted")
    config = json.loads((args.runtime / "runtime-public.json").read_text(encoding="utf-8"))
    key = unprotect_secrets((args.runtime / "validation-key.dpapi").read_bytes())["signing_key"]
    env = os.environ.copy()
    env.update(VIEWER_ENV=os.environ.get("VIEWER_ENV", "development"), DATABASE_URL=settings.database_url,
        DATA_ROOT=str(settings.data_root), AGENT_IMPORT_ENABLED="true", AGENT_API_WORKER_ENABLED="false",
        AGENT_INPUT_SNAPSHOT_ENABLED="true", AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS="300",
        AGENT_CANDIDATE_VERIFICATION_ENABLED="true", AGENT_AUTO_DELIVERY_ENABLED="false",
        AGENT_VERIFICATION_POSTGRES_BIN=config["postgres_bin"], AGENT_VERIFICATION_NODE=config["node"],
        AGENT_VERIFICATION_BROWSER_CACHE=config["browser_cache"], AGENT_VERIFICATION_ORACLE_ROOT=str(args.runtime / "protected-oracles"),
        AGENT_VERIFICATION_SIGNING_KEY=key, PYTHONUTF8="1")
    if args.read_only:
        env.update(AGENT_IMPORT_ENABLED="false", AGENT_API_WORKER_ENABLED="false", AGENT_DELIVERY_READS_ENABLED="true",
            AGENT_CANDIDATE_VERIFICATION_ENABLED="false", OPENAI_API_KEY="", OPENAI_BASE_URL="", OPENAI_MODEL="")
    processes, handles = [], []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        commands = [("api", ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(config["port"])])]
        if not args.read_only:
            commands.append(("worker", ["app.agent_import.worker_main"]))
        for name, command in commands:
            log = (args.runtime / (name + ".log")).open("a", encoding="utf-8")
            handles.append(log)
            processes.append(subprocess.Popen([sys.executable, "-B", "-m", *command], cwd=REPO / "back", env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **flags))
        (args.runtime / "processes.json").write_text(json.dumps({"controller": os.getpid(), "read_only": args.read_only,
            **{name: process.pid for (name, _), process in zip(commands, processes)}}), encoding="utf-8")
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "start"])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browser-cache", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--read-only", action="store_true", help="Start only data/source/MD reads with model connection and Worker disabled")
    args = parser.parse_args()
    args.runtime = args.runtime.resolve()
    prepare(args) if args.action == "prepare" else start(args)
