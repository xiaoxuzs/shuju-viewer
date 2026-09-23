"""Real browser session + upload/path/Case APIs in a new owned SQLite fixture.

The optional Worker check exercises the ordinary unbound queue and must not
manufacture a grant. No production DB/native picker. The dataset-list fixture
is empty; session/upload/Case routes and Worker are product code.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def api_child(port):
    from fastapi import FastAPI
    from app.agent_import.api import router as cases
    from app.agent_import.local_sessions import router as sessions
    from app.api.v1.import_uploads import router as uploads
    from app.agent_import.migrations import ensure_agent_import_schema
    ensure_agent_import_schema()
    app = FastAPI()
    for router in (cases, sessions, uploads):
        app.include_router(router, prefix="/api/v1")
    @app.get("/api/v1/datasets")
    def empty_dataset_fixture():
        return []  # Explicit fixture only, never a data-import acceptance claim.
    @app.get("/health")
    def health():
        return {"status": "ok", "scope": "owned-session-fixture"}
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


def worker_check_child():
    """Exercise ordinary unbound Cases; do not manufacture a model grant."""
    if os.environ.get("VIEWER_ENV") != "test" or os.environ.get("AGENT_MODEL_AUTHORIZATION_REQUIRED") != "true":
        raise RuntimeError("Explicit isolated authorization-enforced test required")
    from app.agent_import.worker import AgentWorker
    from app.agent_import.case_service import CaseService
    from app.agent_import.authorization_ledger import AuthorizationLedger
    service = CaseService()
    cases = service.list_cases()
    if not cases or any(AuthorizationLedger(service.engine).binding(case.case_id) is not None for case in cases):
        raise RuntimeError("This check requires newly submitted unbound Cases, not an existing authorized task")
    worker = AgentWorker(service=service)
    try:
        for _ in range(len(cases)):
            worker.poll_once()
        result = [{"case_id": case.case_id, "status": service.get_case(case.case_id).status.value,
            "verification": service.get_case(case.case_id).verification_payload,
            "model_request_artifacts": sum(a.artifact_type == "model_request" for a in service.list_artifacts(case.case_id))} for case in cases]
        output = Path(os.environ["VIEWER_SESSION_TEST_OUTPUT"]) / "worker-check.json"
        output.write_text(json.dumps({"scope": "real Worker on the two browser-created Cases; no synthetic authorization binding", "cases": result,
            "import_completed": all(r["status"] == "SUCCESS" for r in result)}, indent=2), encoding="utf-8")
    finally:
        worker.graph_runner.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browser-cache", type=Path)
    parser.add_argument("--api-child", type=int)
    parser.add_argument("--worker-check", action="store_true")
    parser.add_argument("--worker-check-child", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "back"))
    if args.api_child:
        return api_child(args.api_child)
    if args.worker_check_child:
        return worker_check_child()
    from app.agent_import.test_storage import create_test_storage
    from app.agent_import.source_code import SourceSnapshot
    from app.agent_import.validation_processes import ProcessLifetime
    root = args.output.resolve()
    identity = create_test_storage(root)
    database_root = Path(tempfile.mkdtemp(prefix="viewer-local-session-db-"))
    data = root / "data"
    source = data / "source"
    source.mkdir(parents=True)
    (source / "measurements.tsv").write_text("id\tvalue\none\t0\ntwo\t\n", encoding="utf-8")
    snapshot = SourceSnapshot.capture(repository)
    snapshot.export(root / "source")
    def port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    api_port, front_port = port(), port()
    origin = f"http://127.0.0.1:{front_port}"
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP") if k in os.environ}
    env.update(VIEWER_ENV="test", DATABASE_URL=f"sqlite+pysqlite:///{(database_root / 'session-test.sqlite').as_posix()}", DATA_ROOT=str(data),
        VIEWER_TEST_STORAGE_ROOT=str(root), VIEWER_TEST_STORAGE_ID=identity, AGENT_API_WORKER_ENABLED="false",
        AGENT_BROWSER_SESSIONS_ENABLED="true", AGENT_BROWSER_ORIGIN=origin, IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT="true",
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PLAYWRIGHT_BROWSERS_PATH=str(args.browser_cache),
        PATH=str(args.node.parent) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32"))
    processes, lives, logs = [], [], []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    def start(command, label, cwd):
        log = (root / (label + ".log")).open("x", encoding="utf-8")
        logs.append(log)
        child = subprocess.Popen([str(v) for v in command], cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
        life = ProcessLifetime()
        life.attach(child)
        lives.append(life)
        processes.append(child)
        return child
    def ready(url, child):
        until = time.monotonic() + 60
        while True:
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            if child.poll() is not None or time.monotonic() >= until:
                raise RuntimeError("Owned session test service did not become ready")
            time.sleep(0.1)
    try:
        api = start([sys.executable, "-B", Path(__file__), "--api-child", api_port], "api", repository)
        ready(f"http://127.0.0.1:{api_port}/health", api)
        front = start([args.node, repository / "front/verification/candidate-server.mjs", root / "source/front", front_port, api_port, snapshot.identity, "a"*64], "frontend", root / "source/front")
        ready(origin, front)
        os.environ.update(env)
        from app.agent_import.local_sessions import create_handoff
        from app.core.db import engine
        handoff = create_handoff(engine, origin=origin)
        browser = start([args.node, repository / "front/verification/local-session-check.mjs"], "browser", repository / "front")
        browser.communicate(json.dumps({"origin": origin, "handoff": handoff, "source": str(source), "output": str(root / "browser.json")}).encode(), timeout=90)
        engine.dispose()
        if browser.returncode:
            raise RuntimeError("Browser session workflow failed; inspect bounded browser.json")
        if args.worker_check:
            from dotenv import dotenv_values
            configured = dotenv_values(repository / "back/.env")
            for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
                value = os.environ.get(name) or configured.get(name)
                if not value:
                    raise RuntimeError("The single API configuration is incomplete; no Worker check started")
                env[name] = value
            configured.clear()
            env.update(AGENT_MODEL_AUTHORIZATION_REQUIRED="true", VIEWER_SESSION_TEST_OUTPUT=str(root))
            worker = start([sys.executable, "-B", Path(__file__), "--worker-check-child"], "worker", repository)
            worker.communicate(timeout=60)
            if worker.returncode:
                raise RuntimeError("Worker check failed; inspect bounded log")
            checked = json.loads((root / "worker-check.json").read_text(encoding="utf-8"))
            if not checked["import_completed"]:
                raise RuntimeError("Ordinary import did not complete; see worker-check.json for the actual blocking stage")
    finally:
        for life in reversed(lives):
            life.close()
        for child in processes:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        for log in logs:
            log.close()
        checked = json.loads((root / "worker-check.json").read_text(encoding="utf-8")) if (root / "worker-check.json").is_file() else None
        (root / "runtime.json").write_text(json.dumps({"code_sha256": snapshot.identity, "processes_stopped": all(p.poll() is not None for p in processes),
            "model_request_artifacts": sum(c["model_request_artifacts"] for c in checked["cases"]) if checked else 0,
            "worker_check_requested": args.worker_check, "import_completed": checked["import_completed"] if checked else None,
            "database_root": str(database_root), "scope": "SQLite real session/upload/Case APIs; optional real Worker check; empty dataset-list fixture; not full scientific-data acceptance"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
