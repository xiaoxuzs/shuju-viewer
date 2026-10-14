"""Owned local runtime for visible browser acceptance; no UI/API state seeding."""
from __future__ import annotations
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
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manual", action="store_true", help="Prepare a blank runtime for user-operated import; do not create a replay fixture")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project / "back"))
    from app.agent_import.test_storage import create_test_storage, protect_secrets
    from app.agent_import.input_assets import freeze_source, content_manifest
    from app.agent_import.source_code import SourceSnapshot
    from app.agent_import.verification import restricted_environment, _port
    from app.agent_import.validation_processes import ProcessLifetime
    from dotenv import dotenv_values
    storage = args.root.resolve()
    identity = create_test_storage(storage)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix="viewer-browser-maxquant-"))
    data = storage / "data"
    data.mkdir()
    os.environ.update(VIEWER_ENV="test", DATABASE_URL=f"sqlite+pysqlite:///{scratch / 'unused.sqlite'}", DATA_ROOT=str(data),
        VIEWER_TEST_STORAGE_ROOT=str(storage), VIEWER_TEST_STORAGE_ID=identity)
    original = args.source.resolve(strict=True)
    retained = freeze_source(original, data / "首次完整来源")
    first_source = data / "首次完整来源/files"
    replay_source = None
    if not args.manual:
        replay_source = data / "固定入口完整副本"
        replay_source.mkdir()
        for relative in retained["files"]:
            target = replay_source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(first_source / relative, target)
        if content_manifest(replay_source) != retained:
            raise RuntimeError("Replay bytes differ from the complete original source")
    from app.fingerprint import compute_dataset_metadata_fingerprint
    fingerprints = [compute_dataset_metadata_fingerprint(path).fingerprint for path in (first_source, replay_source) if path is not None]
    if replay_source is not None and fingerprints[0] == fingerprints[1]:
        raise RuntimeError("Natural file-copy metadata did not create a distinct replay fixture; do not alter deduplication")
    configured = dotenv_values(project / "back/.env")
    connection = {name: os.environ.get(name) or configured.get(name) for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")}
    configured.clear()
    if not all(connection.values()):
        raise RuntimeError("The existing single model connection is not configured")
    snapshot = SourceSnapshot.capture(project)
    workspace = storage / "source"
    snapshot.export(workspace)
    postgres_bin = project / "cjb/runtime/postgresql/bin"
    node = Path(shutil.which("node"))
    browser_cache = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    pg_port, api_port, front_port = _port(), _port(), _port()
    if len({pg_port, api_port, front_port}) != 3:
        raise RuntimeError("Owned runtime ports collided")
    admin_password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    operator, signing = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    password_file = storage / "admin-password"
    password_file.write_text(admin_password, encoding="utf-8")
    pgdata = storage / "postgres"
    environment = restricted_environment(scratch)
    profile = json.loads((project / "back/config/agent-gpt-local.json").read_text(encoding="utf-8"))
    environment.update({**connection, **profile, "VIEWER_ENV": "test",
        "DATABASE_URL": f"postgresql+psycopg://viewer_browser_test:{app_password}@127.0.0.1:{pg_port}/viewer_test_browser_maxquant",
        "DATA_ROOT": str(data), "VIEWER_BUILD_ID": snapshot.identity, "AGENT_SOURCE_ROOT": str(workspace),
        "VIEWER_TEST_STORAGE_ROOT": str(storage), "VIEWER_TEST_STORAGE_ID": identity,
        "AGENT_IMPORT_ENABLED": "true", "AGENT_SOURCE_READ_ENABLED": "false", "AGENT_IMPLEMENTATION_SOURCE_EVIDENCE_ENABLED": "false",
        "AGENT_MODEL_AUTHORIZATION_REQUIRED": "true", "AGENT_INPUT_SNAPSHOT_ENABLED": "true", "AGENT_AUTO_DELIVERY_ENABLED": "false",
        "AGENT_API_WORKER_ENABLED": "false", "AGENT_REVISION_READS_ENABLED": "true", "AGENT_CANDIDATE_VERIFICATION_ENABLED": "true",
        "AGENT_INTERNAL_TOKEN": operator, "AGENT_VERIFICATION_SIGNING_KEY": signing,
        "AGENT_VERIFICATION_POSTGRES_BIN": str(postgres_bin), "AGENT_VERIFICATION_NODE": str(node),
        "AGENT_VERIFICATION_BROWSER_CACHE": str(browser_cache), "AGENT_VERIFICATION_ORACLE_ROOT": str(storage / "protected-oracles"),
        "PLAYWRIGHT_BROWSERS_PATH": str(browser_cache), "IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT": "true",
        "IMPORT_NATIVE_FOLDER_PICKER": "true" if args.manual else "false", "BU_UNIPROT_ENABLED": "false", "BU_FRAGMENT_MATCH_ROOT": str(data / "pfmb"), "PYTHONUTF8": "1"})
    processes, lifetimes, logs = [], [], []
    record = {"status": "STARTING", "code_sha256": snapshot.identity, "source_original": str(original),
        "source_identity": retained["sha256"], "source_files": retained["files"], "metadata_fingerprints": fingerprints,
        "mode": "manual-import-testing" if args.manual else "browser-acceptance",
        "replay_scope": "none; user starts import manually in a blank database" if args.manual else "complete byte-identical real source copy with natural new metadata, not a second independent experiment",
        "origin": f"http://127.0.0.1:{front_port}", "processes": []}
    def launch(argv, name, *, cwd=None, env=None, background=False):
        log = (output / f"{name}.log").open("w", encoding="utf-8")
        logs.append(log)
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        child = subprocess.Popen([str(x) for x in argv], cwd=cwd or storage, env=env or environment,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
        lifetime = ProcessLifetime()
        lifetime.attach(child)
        processes.append(child); lifetimes.append(lifetime)
        record["processes"].append({"name": name, "pid": child.pid, "argv": [str(x) for x in argv]})
        if not background and child.wait(timeout=60):
            raise RuntimeError(name + " failed; inspect retained log")
        return child
    try:
        launch([postgres_bin / "initdb.exe", "-D", pgdata, "-U", "validator_admin", "--auth=scram-sha-256", "--pwfile", password_file, "--encoding=UTF8", "--no-locale"], "initdb", env=restricted_environment(scratch))
        password_file.unlink()
        postgres = launch([postgres_bin / "postgres.exe", "-D", pgdata, "-h", "127.0.0.1", "-p", pg_port, "-c", "shared_buffers=32MB", "-c", "max_connections=32"], "postgres", background=True)
        import psycopg
        from psycopg import sql
        deadline = time.monotonic() + 30
        while True:
            try:
                admin = psycopg.connect(host="127.0.0.1", port=pg_port, dbname="postgres", user="validator_admin", password=admin_password, autocommit=True, connect_timeout=2)
                break
            except psycopg.OperationalError:
                if postgres.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Owned PostgreSQL did not start") from None
                time.sleep(.2)
        with admin:
            if Path(admin.execute("SHOW data_directory").fetchone()[0]).resolve() != pgdata.resolve():
                raise RuntimeError("Owned cluster identity mismatch")
            admin.execute(sql.SQL("CREATE ROLE viewer_browser_test LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Literal(app_password)))
            admin.execute("CREATE DATABASE viewer_test_browser_maxquant OWNER viewer_browser_test")
        with psycopg.connect(host="127.0.0.1", port=pg_port, dbname="viewer_test_browser_maxquant", user="viewer_browser_test", password=app_password) as db:
            db.execute((workspace / "docs/universal_schema.sql").read_text(encoding="utf-8"))
        (storage / "runtime-secrets.dpapi").write_bytes(protect_secrets({"database_password": app_password, "operator_token": operator, "signing_key": signing}))
        launch([sys.executable, "-B", "-m", "app.local_start", "--port", api_port], "normal-startup", cwd=workspace / "back", background=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{api_port}/health", timeout=2) as response:
                    if json.load(response).get("build_id") == snapshot.identity:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned normal startup did not become ready")
            time.sleep(.2)
        launch([node, project / "front/verification/candidate-server.mjs", workspace / "front", front_port, api_port, snapshot.identity, secrets.token_hex(32)], "frontend", cwd=project / "front", background=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                with urlopen(record["origin"], timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned browser frontend did not become ready")
            time.sleep(.2)
        record["status"] = "READY"
        record["source"] = str(first_source)
        record["replay_source"] = str(replay_source) if replay_source is not None else None
        record["browser_cache"] = str(browser_cache)
        (output / "浏览器输入.json").write_text(json.dumps({"origin": record["origin"], "source": str(first_source), "replay_source": record["replay_source"],
            "output": str(output), "browser_cache": str(browser_cache), "max_flow_seconds": 1500}, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "环境.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "READY", "origin": record["origin"], "input": str(output / "浏览器输入.json")}, ensure_ascii=False), flush=True)
        while not (output / "STOP").exists():
            if any(child.poll() is not None for child in processes[-3:]):
                raise RuntimeError("Owned runtime process exited unexpectedly")
            time.sleep(1)
    finally:
        for child in reversed(processes):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
        for lifetime in reversed(lifetimes):
            lifetime.close()
        for log in logs:
            log.close()
        record["processes_stopped"] = True
        (output / "环境.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
