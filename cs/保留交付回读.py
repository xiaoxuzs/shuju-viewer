"""Bounded restart/readback of one owned durable test delivery. Never starts a Worker/model."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--repair-case", help="Guarded candidate-step recovery, preserving the existing Case deadline/budgets")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "back"))
    from app.agent_import.test_storage import unprotect_secrets, validate_test_storage
    from app.agent_import.source_code import SourceSnapshot
    from app.agent_import.validation_processes import ProcessLifetime
    root = args.root.resolve(strict=True)
    config = json.loads((root / "runtime-public.json").read_text(encoding="utf-8"))
    marker = json.loads((root / "test-storage.json").read_text(encoding="utf-8"))
    if not validate_test_storage(Path(config["data"]), str(root), marker["identity"]):
        raise SystemExit("Not an owned managed test delivery")
    if SourceSnapshot.capture(Path(config["source_code"])).identity != config["code_sha256"]:
        raise SystemExit("Retained application snapshot changed")
    secrets = unprotect_secrets((root / "runtime-secrets.dpapi").read_bytes())
    if args.repair_case:
        import shutil
        new_source = root / "recovery-source-01"
        snapshot = SourceSnapshot.capture(repository)
        snapshot.export(new_source)
        node = config["env"]["AGENT_VERIFICATION_NODE"]
        subprocess.run([node, "-e", "require('fs').symlinkSync(process.argv[1],process.argv[2],'junction')", str(repository / "front/node_modules"), str(new_source / "front/node_modules")],
            check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        shutil.copyfile(root / "runtime-public.json", root / "runtime-public-before-recovery.json")
        config.update(source_code=str(new_source), code_sha256=snapshot.identity)
        config["env"].update(AGENT_SOURCE_ROOT=str(new_source), VIEWER_BUILD_ID=snapshot.identity)
        (root / "runtime-public.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    def port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
    pgport, apiport = port(), port()
    scratch = Path(tempfile.mkdtemp(prefix="viewer-retained-readback-"))
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT") if k in os.environ}
    env.update(TEMP=str(scratch), TMP=str(scratch), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    processes, lives, logs = [], [], []
    report = {"scope": "restart of retained test delivery; no model/Worker", "passed": False, "code_sha256": config["code_sha256"]}
    def start(argv, label, child_env):
        log = (scratch / (label + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        p = subprocess.Popen([str(x) for x in argv], cwd=Path(config["source_code"]) / "back", env=child_env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
        processes.append(p)
        lifetime = ProcessLifetime()
        lifetime.attach(p)
        lives.append(lifetime)
        return p
    try:
        pg = start([Path(config["postgres_bin"]) / "postgres.exe", "-D", config["pgdata"], "-h", "127.0.0.1", "-p", pgport], "postgres", env)
        import psycopg
        until = time.monotonic() + 30
        while True:
            try:
                db = psycopg.connect(host="127.0.0.1", port=pgport, dbname=config["database"], user=config["database_user"], password=secrets["database_password"], connect_timeout=2)
                break
            except psycopg.OperationalError:
                if pg.poll() is not None or time.monotonic() > until:
                    raise RuntimeError("Owned retained test database unavailable") from None
                time.sleep(0.2)
        with db:
            if args.repair_case:
                case = db.execute("SELECT case_id,dataset_id,dataset_slug,candidate_zp_path,candidate_zp_sha256,ever_published FROM agent_import_cases WHERE case_id=%s", (args.repair_case,)).fetchone()
            else:
                case = db.execute("SELECT case_id,dataset_id,dataset_slug,candidate_zp_path,candidate_zp_sha256,ever_published FROM agent_import_cases WHERE status='SUCCESS'").fetchone()
            if case is None or (not args.repair_case and not case[5]):
                raise RuntimeError("No published test delivery exists")
            total = db.execute("SELECT count(*) FROM identification_matches WHERE dataset_id=%s", (case[1],)).fetchone()[0]
            if not args.repair_case:
                report["authorization_counters"] = [{"authorization_id": row[0], "calls_used": row[1], "reserved_units": row[2]}
                    for row in db.execute("SELECT authorization_id,calls_used,reserved_units FROM agent_authorizations ORDER BY authorization_id")]
                report["request_outcomes"] = [{"role": row[0], "outcome": row[1], "count": row[2]}
                    for row in db.execute("SELECT role,outcome,count(*) FROM agent_request_reservations GROUP BY role,outcome ORDER BY role,outcome")]
                report["unclosed_experiments"] = db.execute("SELECT count(*) FROM agent_experiments WHERE ended_at IS NULL").fetchone()[0]
                if db.execute("SELECT to_regclass('agent_task_runs')").fetchone()[0]:
                    report["ordinary_task_requests"] = [{"role": row[0], "outcome": row[1], "count": row[2]}
                        for row in db.execute("SELECT role,outcome,count(*) FROM agent_task_requests GROUP BY role,outcome ORDER BY role,outcome")]
                    report["ordinary_tasks"] = [{"task_id": row[0], "kind": row[1], "requests": row[2], "reservation_units": row[3],
                        "policy": json.loads(row[4]), "wall_seconds": row[6]-row[5] if row[6] is not None else None}
                        for row in db.execute("SELECT task_id,kind,request_count,reserved_units,policy_json,created_at,ended_at FROM agent_task_runs ORDER BY created_at")]
            if args.repair_case:
                used_calls = db.execute("SELECT count(*) FROM agent_artifacts WHERE case_id=%s AND artifact_type='model_request'", (case[0],)).fetchone()[0]
                records = [json.loads(line) for line in (root / "evidence/worker.log").read_text(encoding="utf-8").splitlines() if line.startswith('{')]
                charged = next(r["elapsed_seconds"] for r in records if r.get("event") == "worker_resources")
                remaining_calls = int(config["env"].get("VIEWER_TEST_MODEL_CALLS", "12")) - used_calls
                remaining_seconds = int(config["env"].get("VIEWER_TEST_MODEL_SECONDS", "1800")) - charged
                if remaining_calls <= 0 or remaining_seconds <= 0:
                    raise RuntimeError("Original model budget exhausted; no reset is permitted")
                report["model_budget"] = {"previous_calls": used_calls, "remaining_calls": remaining_calls,
                    "previous_worker_wall_charged": charged, "remaining_active_seconds": remaining_seconds}
        child_env = {**config["env"], **env,
            "DATABASE_URL": f"postgresql+psycopg://{config['database_user']}:{secrets['database_password']}@127.0.0.1:{pgport}/{config['database']}",
            "AGENT_INTERNAL_TOKEN": secrets["operator_token"], "AGENT_API_WORKER_ENABLED": "false", "AGENT_IMPORT_ENABLED": "false",
            "AGENT_AUTO_DELIVERY_ENABLED": "false", "AGENT_CANDIDATE_VERIFICATION_ENABLED": "false", "AGENT_SOURCE_READ_ENABLED": "false",
            "AGENT_DELIVERY_READS_ENABLED": "true", "OPENAI_API_KEY": "", "AGENT_TEST_MODEL_ENABLED": "false"}
        if args.repair_case:
            from dotenv import dotenv_values
            values = dotenv_values(repository / "back/.env")
            child_env.update({k: os.environ.get(k) or values.get(k) for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")})
            values.clear()
            child_env.update(AGENT_IMPORT_ENABLED="true", AGENT_AUTO_DELIVERY_ENABLED="true", AGENT_CANDIDATE_VERIFICATION_ENABLED="true",
                AGENT_SOURCE_READ_ENABLED="true", AGENT_VERIFICATION_SIGNING_KEY=secrets["signing_key"],
                VIEWER_TEST_MODEL_CALLS=str(remaining_calls), VIEWER_TEST_MODEL_SECONDS=str(int(remaining_seconds)))
        api = start([config["python"], "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", apiport], "api", child_env)
        def fetch(path, body=None):
            request = Request(f"http://127.0.0.1:{apiport}" + path, data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": "Bearer " + secrets["operator_token"], "Content-Type": "application/json"})
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read(2 * 1024 * 1024))
        until = time.monotonic() + 30
        while True:
            try:
                health = fetch("/health")
                assert health["build_id"] == config["code_sha256"]
                break
            except OSError:
                if api.poll() is not None or time.monotonic() > until:
                    raise RuntimeError("Retained test API unavailable") from None
                time.sleep(0.2)
        if args.repair_case:
            current = fetch("/api/v1/agent-import-cases/" + case[0])
            recovered = fetch(f"/api/v1/agent-import-cases/{case[0]}/recover-execution", {"expected_version": current["version"], "new_code_identity": config["code_sha256"]})
            print(json.dumps({"recovered_status": recovered["status"], "original_deadline": recovered["deadline_at"], "reserved_preserved": recovered["model_tokens_reserved"]}), flush=True)
            worker = start([config["python"], "-B", repository / "cs/GPT正常入口验收.py", "--worker-child"], "recovery-worker", child_env)
            from datetime import datetime, timezone
            deadline = datetime.fromisoformat(recovered["deadline_at"])
            previous = None
            while worker.poll() is None:
                if datetime.now(timezone.utc) >= deadline:
                    raise TimeoutError("The original Case deadline expired; recovery may not extend it")
                state = fetch("/api/v1/agent-import-cases/" + case[0])
                if state["status"] != previous:
                    print(json.dumps({"status": state["status"]}), flush=True)
                    previous = state["status"]
                time.sleep(2)
            state = fetch("/api/v1/agent-import-cases/" + case[0])
            artifacts = fetch("/api/v1/agent-import-cases/" + case[0] + "/artifacts")
            (root / "recovery-case.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            (root / "recovery-artifacts.json").write_text(json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
            report.update(scope="guarded recovery of original normal-entry Case", case_id=case[0], status=state["status"], passed=state["status"] == "SUCCESS")
            if state["status"] == "SUCCESS":
                handover = next(a["structured_payload"]["markdown"] for a in artifacts if a["artifact_type"] == "handover")
                (root / "HANDOVER.md").write_text(handover, encoding="utf-8")
            else:
                raise SystemExit(1)
            return
        prefix = f"/api/v1/datasets/{case[2]}/matches?q_filter=false&decoy=true&sort=match_id&order=asc&page_size=1"
        first, last = fetch(prefix + "&page=1"), fetch(prefix + f"&page={total}")
        if first["total"] != total or last["total"] != total or len(first["items"]) != 1 or len(last["items"]) != 1:
            raise RuntimeError("Retained API cannot read complete scope boundaries")
        import hashlib
        with Path(case[3]).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != case[4]:
            raise RuntimeError("Retained ZP changed")
        assets = fetch(f"/api/v1/agent-import-cases/{case[0]}/source-assets")
        request = Request(f"http://127.0.0.1:{apiport}/api/v1/agent-import-cases/{case[0]}/handover",
                          headers={"Authorization": "Bearer " + secrets["operator_token"]})
        with urlopen(request, timeout=20) as response:
            handover = response.read(256 * 1024)
        if not handover or case[0].encode() not in handover:
            raise RuntimeError("Retained HANDOVER identity missing")
        report["handover_sha256"] = hashlib.sha256(handover).hexdigest()
        # Materialize the already committed authoritative MD in the managed
        # retained delivery, not only a temporary browser download/evidence dir.
        handover_file = root / "HANDOVER.md"
        if handover_file.exists():
            if hashlib.sha256(handover_file.read_bytes()).hexdigest() != report["handover_sha256"]:
                raise RuntimeError("Retained HANDOVER file conflicts with committed identity")
        else:
            with handover_file.open("xb") as stream:
                stream.write(handover)
        report["handover_file"] = "HANDOVER.md"
        asset_reads = []
        for asset in assets:
            request = Request(f"http://127.0.0.1:{apiport}/api/v1/agent-import-cases/{case[0]}/source-assets/{asset['asset_id']}",
                headers={"Authorization": "Bearer " + secrets["operator_token"], "Range": "bytes=0-63"})
            with urlopen(request, timeout=30) as response:
                sample = response.read(64)
                if response.status != 206 or len(sample) != min(64, asset["size_bytes"]):
                    raise RuntimeError("Retained source asset range could not be read")
                asset_reads.append({"asset_id": asset["asset_id"], "bytes_read": len(sample), "full_content_sha256_checked_by_asset_service": asset["sha256"]})
        report.update(passed=True, case_id=case[0], dataset_id=case[1], rows=total, first_match_id=first["items"][0]["id"],
            last_match_id=last["items"][0]["id"], candidate_sha256=digest, accessible_source_assets=len(assets), asset_reads=asset_reads)
    finally:
        for p in reversed(processes[1:]):
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)
        if processes:
            subprocess.run([str(Path(config["postgres_bin"]) / "pg_ctl.exe"), "-D", config["pgdata"], "-m", "fast", "-w", "-t", "15", "stop"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=20, **flags)
        for life in lives:
            life.close()
        for p in processes:
            p.wait(timeout=5)
        for log in logs:
            log.close()
        report["processes_stopped"] = all(p.poll() is not None for p in processes)
        (root / ("recovery-result.json" if args.repair_case else "restart-readback.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
