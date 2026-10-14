"""Restart only this task's retained test DB with a new immutable source snapshot."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    root, output = args.root.resolve(strict=True), args.output.resolve()
    marker = json.loads((root / "test-storage.json").read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="viewer-retained-browser-"))
    os.environ.update(VIEWER_ENV="test", DATABASE_URL=f"sqlite+pysqlite:///{scratch / 'unused.sqlite'}", DATA_ROOT=str(root / "data"),
        VIEWER_TEST_STORAGE_ROOT=str(root), VIEWER_TEST_STORAGE_ID=marker["identity"])
    sys.path.insert(0, str(project / "back"))
    from app.agent_import.test_storage import validate_test_storage, unprotect_secrets
    from app.agent_import.source_code import SourceSnapshot
    from app.agent_import.verification import restricted_environment, _port
    from app.agent_import.validation_processes import ProcessLifetime
    if not validate_test_storage(root / "data", str(root), marker["identity"]):
        raise RuntimeError("Not this task's managed test storage")
    output.mkdir(parents=True, exist_ok=False)
    # Application-owned generated runtime material; never emit plaintext values.
    credentials = unprotect_secrets((root / "runtime-secrets.dpapi").read_bytes())
    snapshot = SourceSnapshot.capture(project)
    workspace = root / ("source-revision-" + snapshot.identity[:12])
    if workspace.exists():
        if SourceSnapshot.capture(workspace).identity != snapshot.identity:
            raise RuntimeError("Existing immutable runtime snapshot changed")
    else:
        snapshot.export(workspace)
    pgdata = root / "postgres"
    postgres_bin = project / "cjb/runtime/postgresql/bin"
    node = Path(shutil.which("node"))
    browser_cache = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    pg_port, api_port, front_port = _port(), _port(), _port()
    if len({pg_port, api_port, front_port}) != 3:
        raise RuntimeError("Owned runtime port collision")
    from dotenv import dotenv_values
    configured = dotenv_values(project / "back/.env")
    connection = {key: os.environ.get(key) or configured.get(key) for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")}
    configured.clear()
    env = restricted_environment(scratch, extra={**connection, **json.loads((project / "back/config/agent-gpt-local.json").read_text()),
        "VIEWER_ENV": "test", "DATABASE_URL": f"postgresql+psycopg://viewer_browser_test:{credentials['database_password']}@127.0.0.1:{pg_port}/viewer_test_browser_maxquant",
        "DATA_ROOT": str(root / "data"), "VIEWER_BUILD_ID": snapshot.identity, "AGENT_SOURCE_ROOT": str(workspace),
        "VIEWER_TEST_STORAGE_ROOT": str(root), "VIEWER_TEST_STORAGE_ID": marker["identity"],
        "AGENT_IMPORT_ENABLED": "true", "AGENT_SOURCE_READ_ENABLED": "false", "AGENT_IMPLEMENTATION_SOURCE_EVIDENCE_ENABLED": "false",
        "AGENT_MODEL_AUTHORIZATION_REQUIRED": "true", "AGENT_INPUT_SNAPSHOT_ENABLED": "true", "AGENT_AUTO_DELIVERY_ENABLED": "false",
        "AGENT_API_WORKER_ENABLED": "false", "AGENT_REVISION_READS_ENABLED": "true", "AGENT_CANDIDATE_VERIFICATION_ENABLED": "true",
        "AGENT_INTERNAL_TOKEN": credentials["operator_token"], "AGENT_VERIFICATION_SIGNING_KEY": credentials["signing_key"],
        "AGENT_VERIFICATION_POSTGRES_BIN": str(postgres_bin), "AGENT_VERIFICATION_NODE": str(node), "AGENT_VERIFICATION_BROWSER_CACHE": str(browser_cache),
        "AGENT_VERIFICATION_ORACLE_ROOT": str(root / "protected-oracles"), "PLAYWRIGHT_BROWSERS_PATH": str(browser_cache),
        "IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT": "true", "IMPORT_NATIVE_FOLDER_PICKER": "false", "BU_UNIPROT_ENABLED": "false",
        "BU_FRAGMENT_MATCH_ROOT": str(root / "data/pfmb"), "PYTHONUTF8": "1"})
    credentials.clear()
    processes, lifetimes, logs = [], [], []
    record = {"status": "STARTING", "origin": f"http://127.0.0.1:{front_port}", "code_sha256": snapshot.identity,
        "retained_test_root": str(root), "processes": [], "scope": "retained task-owned test DB; no import state reset or data reingestion"}
    def launch(argv, name, cwd=None):
        log = (output / (name + ".log")).open("w", encoding="utf-8"); logs.append(log)
        child = subprocess.Popen([str(value) for value in argv], cwd=cwd or root, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        lifetime = ProcessLifetime(); lifetime.attach(child)
        processes.append(child); lifetimes.append(lifetime)
        record["processes"].append({"name": name, "pid": child.pid})
        return child
    try:
        postgres = launch([postgres_bin / "postgres.exe", "-D", pgdata, "-h", "127.0.0.1", "-p", pg_port], "postgres")
        import psycopg
        end = time.monotonic() + 45
        while True:
            try:
                with psycopg.connect(env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://"), connect_timeout=2) as db:
                    pid_record = (pgdata / "postmaster.pid").read_text(encoding="utf-8").splitlines()
                    if int(pid_record[0]) != postgres.pid or Path(pid_record[1]).resolve() != pgdata.resolve() or int(pid_record[3]) != pg_port:
                        raise RuntimeError("Owned retained cluster identity mismatch")
                    record["datasets_retained"] = db.execute("SELECT count(*) FROM datasets").fetchone()[0]
                break
            except psycopg.OperationalError:
                if postgres.poll() is not None or time.monotonic() > end:
                    raise RuntimeError("Owned retained PostgreSQL unavailable") from None
                time.sleep(.2)
        launch([sys.executable, "-B", "-m", "app.local_start", "--port", api_port], "normal-startup", workspace / "back")
        end = time.monotonic() + 60
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{api_port}/health", timeout=2) as response:
                    if json.load(response).get("build_id") == snapshot.identity: break
            except OSError: pass
            if time.monotonic() > end: raise RuntimeError("Owned retained API unavailable")
            time.sleep(.2)
        launch([node, project / "front/verification/candidate-server.mjs", workspace / "front", front_port, api_port, snapshot.identity, secrets.token_hex(32)], "frontend", project / "front")
        end = time.monotonic() + 60
        while True:
            try:
                with urlopen(record["origin"], timeout=2) as response:
                    if response.status == 200: break
            except OSError: pass
            if time.monotonic() > end: raise RuntimeError("Owned retained frontend unavailable")
            time.sleep(.2)
        record["status"] = "READY"
        (output / "环境.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        while not (output / "STOP").exists():
            if any(child.poll() is not None for child in processes): raise RuntimeError("Owned runtime stopped unexpectedly")
            time.sleep(1)
    finally:
        for child in reversed(processes[1:]):
            if child.poll() is None: child.terminate(); child.wait(timeout=15)
        subprocess.run([str(postgres_bin / "pg_ctl.exe"), "-D", str(pgdata), "stop", "-m", "fast", "-w"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        for child in processes:
            if child.poll() is None: child.terminate(); child.wait(timeout=15)
        for lifetime in lifetimes: lifetime.close()
        for log in logs: log.close()
        record["processes_stopped"] = True
        (output / "环境.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
