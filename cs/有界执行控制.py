"""Trusted controller for the explicitly retained test DB; never prints secrets.

register/status do not activate an experiment or call a model. model-probe is
one finite request, atomically charged in that SAME business database.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

GRANT = "viewer-20260917-u01-u12-01"
CASE = "6adfa2e5-a8b4-47ba-88cb-8088dbb01333"


@contextmanager
def retained_database(root, repository):
    from app.agent_import.test_storage import unprotect_secrets, validate_test_storage
    from app.agent_import.validation_processes import ProcessLifetime
    import psycopg
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    config = json.loads((root / "runtime-public.json").read_text(encoding="utf-8"))
    marker = json.loads((root / "test-storage.json").read_text(encoding="utf-8"))
    if not validate_test_storage(Path(config["data"]), str(root), marker["identity"]):
        raise ValueError("Managed test storage ownership mismatch")
    if Path(config["pgdata"]).resolve() != root / "postgres" or not config["database"].startswith("viewer_test_"):
        raise ValueError("Retained test database identity mismatch")
    secrets = unprotect_secrets((root / "runtime-secrets.dpapi").read_bytes())
    evidence = root / "evidence" / GRANT
    evidence.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    scratch = Path(tempfile.mkdtemp(prefix="viewer-authorized-controller-"))
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT") if k in os.environ}
    env.update(TEMP=str(scratch), TMP=str(scratch))
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    lifetime = ProcessLifetime()
    process = engine = None
    with (evidence / f"postgres-{time.time_ns()}.log").open("x", encoding="utf-8") as log:
        try:
            process = subprocess.Popen([str(Path(config["postgres_bin"]) / "postgres.exe"), "-D", config["pgdata"], "-h", "127.0.0.1", "-p", str(port)],
                env=env, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
            lifetime.attach(process)
            end = time.monotonic() + 30
            while True:
                try:
                    with psycopg.connect(host="127.0.0.1", port=port, dbname=config["database"], user=config["database_user"],
                            password=secrets["database_password"], connect_timeout=2) as db:
                        # The retained application role deliberately cannot SHOW
                        # data_directory. Bind the owned process to its pidfile,
                        # startup -D path and SQL server port, without elevating it.
                        pidfile = (root / "postgres/postmaster.pid").read_text(encoding="utf-8").splitlines()
                        server_port = db.execute("SELECT inet_server_port()").fetchone()[0]
                        if int(pidfile[0]) != process.pid or Path(pidfile[1]).resolve() != root / "postgres" or int(pidfile[3]) != port or server_port != port:
                            raise ValueError("Running PostgreSQL cluster differs from retained directory")
                    break
                except psycopg.OperationalError:
                    if process.poll() is not None or time.monotonic() > end:
                        raise RuntimeError("Owned retained test PostgreSQL failed to start") from None
                    time.sleep(0.2)
            url = URL.create("postgresql+psycopg", username=config["database_user"], password=secrets["database_password"], host="127.0.0.1", port=port, database=config["database"])
            os.environ.update(VIEWER_ENV="test", DATABASE_URL=url.render_as_string(hide_password=False), DATA_ROOT=config["data"],
                VIEWER_TEST_STORAGE_ROOT=str(root), VIEWER_TEST_STORAGE_ID=marker["identity"], AGENT_API_WORKER_ENABLED="false",
                AGENT_AUTO_DELIVERY_ENABLED="false", AGENT_CANDIDATE_VERIFICATION_ENABLED="false", AGENT_MODEL_AUTHORIZATION_REQUIRED="true")
            from app.agent_import.local_profile import apply_local_gpt_profile
            apply_local_gpt_profile()
            engine = create_engine(url, pool_pre_ping=True)
            yield engine, evidence, config, secrets
        finally:
            if engine is not None:
                engine.dispose()
            if process is not None and process.poll() is None:
                subprocess.run([str(Path(config["postgres_bin"]) / "pg_ctl.exe"), "-D", config["pgdata"], "-m", "fast", "-w", "-t", "15", "stop"],
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, **flags)
            lifetime.close()
            if process is not None:
                process.wait(timeout=5)
            secrets.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "status", "model-probe"))
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    root = args.root.resolve(strict=True)
    if root != repository / ".viewer-test-deliveries/diaclip-20260916-01":
        raise SystemExit("This one-time authority names only the retained DIA-CLIP test directory")
    sys.path.insert(0, str(repository / "back"))
    with retained_database(root, repository) as (engine, evidence, config, _secrets):
        from sqlalchemy import text
        from app.agent_import.authorization_ledger import AuthorizationLedger, authority_scope, route_identity
        from app.agent_import.model_routing import route_for
        from app.agent_import.migrations import ensure_agent_import_schema
        ensure_agent_import_schema(engine)
        ledger = AuthorizationLedger(engine)
        route = route_for("research")
        contract = {"request_limit": 24, "reservation_limit": 24 * (196608 + 4096), "active_seconds": 10800,
            "experiment_seconds": 3600, "output_limit": 4096,
            "route_sha256": route_identity(route.base_url.rstrip("/") + "/chat/completions", route.model),
            "roles": ["research", "implementation", "review", "initial_engineering", "maintenance"],
            "authorization_basis": "User U01-U12 one-time authorization 2026-09-17; no production, no system installation, no dotenv edits"}
        if args.action == "register":
            ledger.register(GRANT, contract)
        with engine.connect() as db:
            case = dict(db.execute(text("SELECT case_id,status,version,context_revision,dataset_id,ever_published,deadline_at,model_tokens_reserved FROM agent_import_cases WHERE case_id=:id"), {"id": CASE}).mappings().one())
            calls = db.execute(text("SELECT count(*) FROM agent_artifacts WHERE case_id=:id AND artifact_type='model_request'"), {"id": CASE}).scalar_one()
        record = {"scope": args.action, "case": case, "historical_recorded_calls": calls, "configured_model_declaration": route.model,
                  "recovery_window_activated": False}
        if args.action == "model-probe":
            experiment = ledger.begin_experiment(GRANT, "Current gateway one-request contract probe; synthetic only", 240)
            lineage = ledger.bind_case(GRANT, "gateway-contract-probe-01", "synthetic-zero-null-v1", call_limit=1, unit_limit=200000)
            try:
                from app.agent_import.model_provider import _chat_json
                with authority_scope(ledger, GRANT, experiment, lineage):
                    response = _chat_json(base_url=route.base_url, api_key=route.api_key, model=route.model, timeout=180,
                        system_prompt="Return only JSON. Preserve zero and null; do not infer missing quantities.",
                        payload={"values": [0, None], "required_result": {"zero_count": 1, "missing_count": 1}}, max_tokens=512, role="research")
                    record["contract_passed"] = response == {"zero_count": 1, "missing_count": 1}
            except Exception as exc:
                record.update(contract_passed=False, failure_code=getattr(exc, "code", None), failure_type=type(exc).__name__)
            finally:
                ledger.end_experiment(GRANT, experiment, "Synchronous model transport terminated; no experiment child remains")
        record["authorization"] = ledger.status(GRANT)
        record["postgres_version"] = engine.dialect.server_version_info
        (evidence / f"{args.action}-{time.time_ns()}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
