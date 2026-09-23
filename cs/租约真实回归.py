"""Probe lease renewal in a fresh schema of this task's stopped, owned test cluster."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inspect-case", type=str)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "back"))
    from app.agent_import.test_storage import unprotect_secrets, validate_test_storage
    root = args.root.resolve(strict=True)
    config = json.loads((root / "runtime-public.json").read_text())
    marker = json.loads((root / "test-storage.json").read_text())
    assert validate_test_storage(Path(config["data"]), str(root), marker["identity"])
    secret = unprotect_secrets((root / "runtime-secrets.dpapi").read_bytes())
    temporary = Path(tempfile.mkdtemp(prefix="viewer-lease-probe-"))
    os.environ.update(VIEWER_ENV="test", DATABASE_URL=f"sqlite+pysqlite:///{(temporary / 'unused.sqlite').as_posix()}", DATA_ROOT=str(temporary))
    from app.agent_import.verification import _port, restricted_environment
    from app.agent_import.validation_processes import ProcessLifetime
    from app.agent_import.case_service import CaseService
    from app.agent_import.migrations import ensure_agent_import_schema
    from app.agent_import.worker import _LeaseHeartbeat
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    import psycopg
    from psycopg import sql
    port = _port()
    env = restricted_environment(temporary)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with (temporary / "postgres.log").open("w") as log:
        process = subprocess.Popen([str(Path(config["postgres_bin"]) / "postgres.exe"), "-D", config["pgdata"], "-h", "127.0.0.1", "-p", str(port)],
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **flags)
        life = ProcessLifetime()
        life.attach(process)
        try:
            until = time.monotonic() + 30
            while True:
                try:
                    connection = psycopg.connect(host="127.0.0.1", port=port, dbname=config["database"], user=config["database_user"], password=secret["database_password"], autocommit=True, connect_timeout=2)
                    break
                except psycopg.OperationalError:
                    if time.monotonic() > until:
                        raise RuntimeError("Owned database unavailable") from None
                    time.sleep(.2)
            schema = "lease_probe_" + uuid.uuid4().hex
            with connection:
                if args.inspect_case:
                    attempts = connection.execute("SELECT failure_code,result FROM public.agent_attempts WHERE case_id=%s ORDER BY started_at", (args.inspect_case,)).fetchall()
                    messages = connection.execute("SELECT content FROM public.agent_messages WHERE case_id=%s AND sender_type='SYSTEM' AND message_kind='EVIDENCE' ORDER BY sequence_no", (args.inspect_case,)).fetchall()
                    print(json.dumps({"original_attempts": attempts, "system_failures": messages}, ensure_ascii=False), flush=True)
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            url = URL.create("postgresql+psycopg", username=config["database_user"], password=secret["database_password"], host="127.0.0.1", port=port, database=config["database"])
            engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
            try:
                ensure_agent_import_schema(engine)
                service = CaseService(engine)
                case = service.create_case(source_ref=str(temporary), dataset_fingerprint="1" * 32, analysis_category="BOTTOM_UP", source_profile="lease-probe", format_details=None)
                claim = service.claim_next(worker_id="lease-probe", lease_seconds=3)
                direct = service.renew_lease(case.case_id, worker_id="lease-probe", lease_seconds=3, lease_token=claim.lease_token)
                before = service.get_case(case.case_id).lease_expires_at
                with _LeaseHeartbeat(service=service, case_id=case.case_id, worker_id="lease-probe", lease_seconds=3, lease_token=claim.lease_token):
                    time.sleep(5)
                    after = service.get_case(case.case_id).lease_expires_at
                    try:
                        service.check_execution(case.case_id, claim.lease_token)
                        valid = True
                    except Exception:
                        valid = False
                result = {"direct_renewal_returned": direct, "before": before, "after": after, "extended": after > before,
                          "valid_after_original_expiry": valid, "schema": schema, "does_not_modify_real_case": True}
                (root / "lease-probe.json").write_text(json.dumps(result, indent=2))
                print(json.dumps(result))
            finally:
                engine.dispose()
        finally:
            subprocess.run([str(Path(config["postgres_bin"]) / "pg_ctl.exe"), "-D", config["pgdata"], "-m", "fast", "-w", "stop"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, **flags)
            life.close()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
