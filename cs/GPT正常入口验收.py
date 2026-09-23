"""Normal HTTP Case + independent existing Worker, on a fresh synthetic test runtime.

Default uses the configured model. --fixture-model explicitly substitutes ONLY
the HTTP model transport, for product-wiring acceptance (never real GPT evidence).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def worker_child():
    from app.agent_import.worker import AgentWorker
    from app.agent_import.model_audit import diagnostic_budget, model_audit_scope
    legacy = os.environ.get("VIEWER_LEGACY_EXPERIMENT") == "true"
    worker = AgentWorker(legacy_experiments=legacy)
    started = time.monotonic()
    def audit(record):
        print(json.dumps(record), flush=True)
    audit_context = diagnostic_budget(audit, calls=int(os.environ["VIEWER_TEST_MODEL_CALLS"]), seconds=int(os.environ["VIEWER_TEST_MODEL_SECONDS"])) if legacy else model_audit_scope(audit)
    with audit_context:
        try:
            for _ in range(3):
                if not worker.poll_once():
                    break
        finally:
            worker.graph_runner.close()
            from app.agent_import.verification_metrics import peak_rss_bytes
            print(json.dumps({"event": "worker_resources", "elapsed_seconds": time.monotonic()-started, "peak_rss_bytes": peak_rss_bytes()}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browser-cache", type=Path)
    parser.add_argument("--worker-child", action="store_true")
    parser.add_argument("--fixture-model", action="store_true")
    parser.add_argument("--browser-entry", action="store_true")
    parser.add_argument("--blank-format", action="store_true", help="Submit only the directory/files, leaving analysis automatic and format hints empty")
    parser.add_argument("--normal-launcher", action="store_true", help="Use the same normal local startup as start-back; empty independent-contract store, manual browser approval, no per-Case preparation")
    parser.add_argument("--max-flow-seconds", type=int, default=1200, help="Browser acceptance wall window, at most 1500 seconds; not a product/model grant")
    parser.add_argument("--source", type=Path, help="Complete real source directory; no record slicing")
    parser.add_argument("--oracle", type=Path, help="Developer/operator-owned v2 source contract, never a model plan")
    parser.add_argument("--delivery-root", type=Path, help="New durable managed test delivery root")
    args = parser.parse_args()
    if not 60 <= args.max_flow_seconds <= 1500:
        raise SystemExit("Acceptance observation window must be between60 and1500 seconds")
    if args.worker_child:
        if os.environ.get("VIEWER_ENV") != "test" or not os.environ.get("VIEWER_BUILD_ID"):
            raise SystemExit("Only an explicitly identified test Worker is allowed")
        sys.path.insert(0, str(Path.cwd()))
        worker_child()
        return
    if not all((args.output, args.postgres_bin, args.node, args.browser_cache)):
        raise SystemExit("Explicit isolated tool paths and output are required")
    if args.fixture_model and args.source:
        raise SystemExit("Synthetic transport cannot stand in for real-source/model acceptance")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "back"))
    from app.agent_import.test_storage import create_test_storage, protect_secrets
    if args.source and ((not args.oracle and not args.normal_launcher) or not args.delivery_root):
        raise SystemExit("Real sources require an independent oracle and durable test delivery root")
    if args.normal_launcher and (bool(args.source) == bool(args.fixture_model) or not args.browser_entry or not args.blank_format or args.oracle):
        raise SystemExit("Normal-launcher verification requires blank-format browser entry and either a complete real source or an explicit synthetic transport fixture; no caller oracle")
    scratch = Path(tempfile.mkdtemp(prefix="viewer-gpt-normal-"))
    storage_id = create_test_storage(args.delivery_root.resolve()) if args.delivery_root else None
    temporary = args.delivery_root.resolve() if args.delivery_root else scratch
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = temporary / "data"
    data.mkdir()
    if storage_id:
        os.environ.update({"VIEWER_TEST_STORAGE_ROOT": str(temporary), "VIEWER_TEST_STORAGE_ID": storage_id})
    os.environ.update({"VIEWER_ENV": "test", "DATABASE_URL": f"sqlite+pysqlite:///{(scratch / 'unused.sqlite').as_posix()}", "DATA_ROOT": str(data)})
    sys.path.insert(0, str(root / "back"))
    if args.fixture_model:
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            fixture_port = sock.getsockname()[1]
        model_env = {"OPENAI_API_KEY": "fixture-only-no-real-credential", "OPENAI_BASE_URL": f"http://127.0.0.1:{fixture_port}/_test", "OPENAI_MODEL": "gpt-test-fixture"}
    else:
        from dotenv import dotenv_values
        configured = dotenv_values(root / "back/.env")
        model_env = {key: os.environ.get(key) or configured.get(key) for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")}
        configured.clear()
    if not all(model_env.values()) or not model_env["OPENAI_MODEL"].startswith("gpt-"):
        raise SystemExit("An explicitly configured GPT route is required; no fallback")
    from app.agent_import.source_code import SourceSnapshot, canonical_bytes, digest_bytes
    from app.agent_import.input_assets import content_manifest, freeze_source
    from app.agent_import.verification import AcceptanceContract, restricted_environment, _port, load_acceptance_contract
    from app.agent_import.validation_processes import ProcessLifetime
    from app.agent_import.local_profile import apply_local_gpt_profile
    snapshot = SourceSnapshot.capture(root)
    workspace = temporary / "source"
    snapshot.export(workspace)
    source = data / "submitted"
    source.mkdir()
    (source / "unknown-results.tsv").write_text("record\trun\tsequence\tproteins\tintensity\none\trun-a\tPEPTIDE\tP1\t0\ntwo\trun-b\tANOTHER\tP2\t\n", encoding="utf-8")
    details = "Synthetic fixture. Each record is one identification. record is the identification source ID; run is the measurement run; sequence is peptide sequence; proteins is the protein accession. intensity is the supplied identification intensity with no known unit. Preserve zero and missing independently. No RT, q-value, decoy, spectra, FASTA or annotations were supplied. Required views: bu.matches and bu.peptides. Preserve the original file."
    profile_name = "synthetic-gpt-normal-entry"
    if args.source:
        (source / "unknown-results.tsv").unlink()  # Only this harness's just-created synthetic placeholder.
        retained = freeze_source(args.source.resolve(strict=True), data / "submitted-real")
        source = data / "submitted-real/files"
        profile_name = "complete-diaclip-fdr-source"
        details = "Preserve the complete supplied DIA-CLIP FDR experiment and companion mzML: every reported precursor identification row, including decoys and failed source flags, without re-running search or FDR. Preserve all original fields and files. Required views: bu.matches, bu.peptides, bu.proteins and identification quantification. Protein.Names/Genes are aggregate row annotations: preserve them in source_fields rather than assigning aggregates to each protein. Protein.Group is one group identity with its reported member accessions; Protein.Ids are separate identification associations. Use the registered Reader's evidenced units/acquisition contract. Preserve duplicate source identifiers with a declared record identity; do not drop duplicates. Do not invent a PSM-to-spectrum link when no source scan identity exists. Preserve DIAClip.Quantity as identification-level source intensity with its original metric name; normalization, channel and sample stay absent unless supplied."
    if args.blank_format:
        profile_name, details = "Unknown format", None
    source_hash = content_manifest(source)["sha256"]
    requirement_hash = digest_bytes(canonical_bytes({"analysis_category": "AUTO" if args.blank_format else "BOTTOM_UP", "source_profile": profile_name, "format_details": details, "user_messages": []}))
    oracle_root = temporary / "protected-oracles"
    oracle_root.mkdir()
    oracle = AcceptanceContract(source_identity=source_hash, requirements_sha256=requirement_hash,
        source_evidence="Independent synthetic source specification: one/PEPTIDE is zero; two/ANOTHER is missing; both RT and quantification unit are unknown. Two distinct table-only runs. No spectra/q-value/decoy/FASTA.",
        scope="all two synthetic rows, normal HTTP entry and actual GPT Worker", total_matches=2,
        matches=[{"source_record_id": "one", "sequence": "PEPTIDE", "rt_minutes": None, "quantification_values": [0.0], "quantification_units": [None]},
                 {"source_record_id": "two", "sequence": "ANOTHER", "rt_minutes": None, "quantification_values": [None], "quantification_units": [None]}])
    if args.fixture_model:
        from app.agent_import.verification_full import FullAcceptanceContract, TableExpectation
        oracle = FullAcceptanceContract(source_identity=source_hash, requirements_sha256=requirement_hash,
            source_evidence=oracle.source_evidence, scope="all two synthetic rows; substitute model transport, actual product Worker; no real GPT",
            table=TableExpectation(relative_path="unknown-results.tsv", reader="delimited", id_column="record", run_column="run",
                sequence_column="sequence", proteins_column="proteins", quantity_column="intensity", quantity_unit=None,
                semantics_evidence="Independent fixture contract: identification intensity with unknown unit, no channel, no sample; zero and missing differ."),
            source_roles={"unknown-results.tsv": "identifications"}, batch_size=1)
    if args.oracle:
        oracle = load_acceptance_contract(args.oracle.read_text(encoding="utf-8"))
        if oracle.schema_version != 2 or oracle.source_identity != source_hash:
            raise ValueError("Real-source contract does not match the complete frozen source")
        oracle = oracle.model_copy(update={"requirements_sha256": requirement_hash})
    if not args.normal_launcher or args.fixture_model:
        (oracle_root / f"{source_hash}-{requirement_hash}.json").write_text(oracle.model_dump_json(), encoding="utf-8")
    pg_port, api_port, front_port = _port(), _port(), _port()
    if pg_port == api_port:
        raise RuntimeError("Port collision")
    control = secrets.token_urlsafe(32)
    admin_password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    password_file = temporary / "admin-password"
    password_file.write_text(admin_password, encoding="utf-8")
    pgdata = temporary / "postgres"
    base_env = restricted_environment(scratch)
    processes, lifetimes, logs = [], [], []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    record = {"scope": "synthetic normal-entry only; no production or real experimental source", "code_sha256": snapshot.identity,
              "temporary_root": str(temporary), "execution_policy": "server_task_settings_no_grant", "status": "FAILED", "commands": []}
    record.update(model_transport="local synthetic substitute" if args.fixture_model else "configured GPT", browser_entry=args.browser_entry)
    if args.fixture_model:
        record["scope"] = "synthetic transport; real app.main/standalone Worker/PG/HTTP/Writer/browser; NOT real GPT or MaxQuant"
    if args.source:
        record.update(scope=oracle.scope, source_identity=source_hash, source_files=retained["files"],
                      durable_test_delivery=True, retention="explicit operator removal only", source_original=str(args.source.resolve()))
    if args.normal_launcher:
        record.update(scope=("Synthetic local transport only; normal startup and real browser/PG/Writer; protected fixture expectations, NOT GPT/MaxQuant" if args.fixture_model else
            "Complete real source; normal local launcher and new browser Case; independent contract produced by product code, no prebuilt candidate/research/oracle"),
            source_contract_precreated=bool(args.fixture_model), reused_case=False, reused_research=False, reused_candidate=False)
    def launch(command, name, *, env=None, cwd=None, background=False):
        log = (output / (name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen([str(x) for x in command], cwd=cwd or temporary, env=env or base_env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
        processes.append(process)
        lifetime = ProcessLifetime()
        lifetime.attach(process)
        lifetimes.append(lifetime)
        record["commands"].append({"name": name, "pid": process.pid, "argv": [str(x) for x in command]})
        if not background:
            if process.wait(timeout=60) != 0:
                raise RuntimeError(name + " failed; retained log")
        return process
    def http(path, payload=None, raw=False):
        request = Request(f"http://127.0.0.1:{api_port}" + path,
            data=canonical_bytes(payload) if payload is not None else None,
            headers={"Authorization": "Bearer " + control, "Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            data_bytes = response.read(8 * 1024 * 1024)
        return data_bytes if raw else json.loads(data_bytes)
    postgres = None
    try:
        # Dependency junction is for trusted code only; not a sandbox or source-code replacement.
        if not args.browser_entry:
            launch([args.node, "-e", "require('fs').symlinkSync(process.argv[1],process.argv[2],'junction')",
                    root / "front/node_modules", workspace / "front/node_modules"], "dependencies")
        launch([args.postgres_bin / "initdb.exe", "-D", pgdata, "-U", "validator_admin", "--auth=scram-sha-256", "--pwfile", password_file, "--encoding=UTF8", "--no-locale"], "initdb")
        password_file.unlink()
        postgres = launch([args.postgres_bin / "postgres.exe", "-D", pgdata, "-h", "127.0.0.1", "-p", pg_port, "-c", "shared_buffers=32MB", "-c", "max_connections=32"], "postgres", background=True)
        import psycopg
        from psycopg import sql
        until = time.monotonic() + 30
        while True:
            try:
                connection = psycopg.connect(host="127.0.0.1", port=pg_port, dbname="postgres", user="validator_admin", password=admin_password, autocommit=True, connect_timeout=2)
                break
            except psycopg.OperationalError:
                if time.monotonic() > until or postgres.poll() is not None:
                    raise RuntimeError("Owned test cluster unavailable") from None
                time.sleep(0.2)
        with connection:
            assert Path(connection.execute("SHOW data_directory").fetchone()[0]).resolve() == pgdata.resolve()
            connection.execute(sql.SQL("CREATE ROLE viewer_gpt_test LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Literal(app_password)))
            connection.execute("CREATE DATABASE viewer_test_gpt OWNER viewer_gpt_test")
        with psycopg.connect(host="127.0.0.1", port=pg_port, dbname="viewer_test_gpt", user="viewer_gpt_test", password=app_password) as database:
            database.execute((workspace / "docs/universal_schema.sql").read_text(encoding="utf-8"))
            assert not any(database.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
        profile = json.loads((root / "back/config/agent-gpt-local.json").read_text())
        env = restricted_environment(scratch, extra={**model_env, **profile,
            "VIEWER_ENV": "test", "DATABASE_URL": f"postgresql+psycopg://viewer_gpt_test:{app_password}@127.0.0.1:{pg_port}/viewer_test_gpt", "DATA_ROOT": str(data),
            "VIEWER_BUILD_ID": snapshot.identity, "AGENT_SOURCE_ROOT": str(workspace), "AGENT_IMPORT_ENABLED": "true",
            "AGENT_SOURCE_READ_ENABLED": "false", "AGENT_INPUT_SNAPSHOT_ENABLED": "true", "AGENT_AUTO_DELIVERY_ENABLED": "true",
            "AGENT_CANDIDATE_VERIFICATION_ENABLED": "true", "AGENT_INTERNAL_TOKEN": control, "AGENT_CASE_DEADLINE_SECONDS": "600",
            "AGENT_VERIFICATION_POSTGRES_BIN": str(args.postgres_bin.resolve()), "AGENT_VERIFICATION_NODE": str(args.node.resolve()),
            "AGENT_VERIFICATION_BROWSER_CACHE": str(args.browser_cache.resolve()), "AGENT_VERIFICATION_ORACLE_ROOT": str(oracle_root),
            "AGENT_VERIFICATION_SIGNING_KEY": secrets.token_urlsafe(48), "IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT": "true",
            "IMPORT_NATIVE_FOLDER_PICKER": "false", "BU_UNIPROT_ENABLED": "false", "BU_FRAGMENT_MATCH_ROOT": str(data / "pfmb")})
        origin = f"http://127.0.0.1:{front_port}"
        env.update(AGENT_API_WORKER_ENABLED="false", AGENT_MODEL_AUTHORIZATION_REQUIRED="true")
        if storage_id:
            env.update(VIEWER_TEST_STORAGE_ROOT=str(temporary), VIEWER_TEST_STORAGE_ID=storage_id)
        if args.browser_entry:
            env.update(PLAYWRIGHT_BROWSERS_PATH=str(args.browser_cache))
        if args.fixture_model:
            env.update(AGENT_TEST_MODEL_ENABLED="true")
            launch([sys.executable, "-B", root / "cs/智能导入传输夹具.py", fixture_port], "fixture-model", env=env, cwd=workspace / "back", background=True)
            check_env = {**env, "VIEWER_TASK_TEST_URL": env["DATABASE_URL"], "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            launch([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q", "tests/test_agent_task_runtime.py",
                    "--junitxml=" + str(output / "task-policy-pg.xml")], "task-policy-pg", env=check_env, cwd=workspace / "back")
        if storage_id:
            env.update(VIEWER_TEST_STORAGE_ROOT=str(temporary), VIEWER_TEST_STORAGE_ID=storage_id)
        if args.source and not args.normal_launcher:
            env.update(AGENT_SOURCE_READ_ENABLED="true", AGENT_IMPLEMENTATION_SOURCE_EVIDENCE_ENABLED="true",
                       AGENT_CASE_DEADLINE_SECONDS="3600", AGENT_CASE_TOKEN_BUDGET="2000000",
                       VIEWER_TEST_MODEL_CALLS="12", VIEWER_TEST_MODEL_SECONDS="1800", AGENT_CASE_PROCESS_MEMORY_BUDGET_BYTES=str(6*1024**3))
        if args.normal_launcher:
            env.pop("AGENT_CASE_DEADLINE_SECONDS", None)
            env.pop("AGENT_CASE_TOKEN_BUDGET", None)
            env.update(AGENT_AUTO_DELIVERY_ENABLED="false",
                       AGENT_SOURCE_READ_ENABLED="false", AGENT_IMPLEMENTATION_SOURCE_EVIDENCE_ENABLED="false")
        if storage_id:
            secrets_record = {"database_password": app_password, "operator_token": control, "signing_key": env["AGENT_VERIFICATION_SIGNING_KEY"]}
            (temporary / "runtime-secrets.dpapi").write_bytes(protect_secrets(secrets_record))
            public_env = {k: v for k, v in env.items() if k not in {"DATABASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_INTERNAL_TOKEN", "AGENT_VERIFICATION_SIGNING_KEY"}}
            (temporary / "runtime-public.json").write_text(json.dumps({"env": public_env, "postgres_bin": str(args.postgres_bin.resolve()),
                "python": sys.executable, "data": str(data), "source_code": str(workspace), "pgdata": str(pgdata),
                "code_sha256": snapshot.identity, "database": "viewer_test_gpt", "database_user": "viewer_gpt_test"}, indent=2), encoding="utf-8")
        api_command = [sys.executable, "-B", "-m", "app.local_start", "--port", api_port] if args.normal_launcher else [sys.executable, "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", api_port]
        api = launch(api_command, "api", env=env, cwd=workspace / "back", background=True)
        until = time.monotonic() + 30
        while True:
            try:
                health = http("/health")
                assert health["build_id"] == snapshot.identity
                break
            except OSError:
                if api.poll() is not None or time.monotonic() > until:
                    raise RuntimeError("Owned test API unavailable") from None
                time.sleep(0.2)
        if args.browser_entry:
            launch([args.node, root / "front/verification/candidate-server.mjs", workspace / "front", front_port, api_port, snapshot.identity, "b"*64],
                   "frontend", env=env, cwd=workspace / "front", background=True)
            until = time.monotonic() + 60
            while True:
                try:
                    with urlopen(origin, timeout=2) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if time.monotonic() > until:
                        raise RuntimeError("Owned frontend unavailable") from None
                    time.sleep(.2)
            with (output / "browser.log").open("w", encoding="utf-8") as browser_log:
                browser = subprocess.Popen([str(args.node), str(root / "front/verification/product-import-check.mjs")],
                    env=env, cwd=root / "front", stdin=subprocess.PIPE, stdout=browser_log, stderr=subprocess.STDOUT, **flags)
                processes.append(browser)
                lifetime = ProcessLifetime()
                lifetime.attach(browser)
                lifetimes.append(lifetime)
                browser.communicate(canonical_bytes({"origin": origin, "source": str(source), "profile": profile_name,
                    "blank_format": args.blank_format, "outside_source": str(workspace),
                    "follow_to_delivery": args.normal_launcher, "real_source": bool(args.source), "max_flow_seconds": args.max_flow_seconds,
                    "details": details, "output": str(output / "browser.json")}), timeout=args.max_flow_seconds + 30 if args.normal_launcher else 90)
                if browser.returncode:
                    failed_browser = json.loads((output / "browser.json").read_text(encoding="utf-8"))
                    if failed_browser.get("timing_target_met") is False:
                        record["status"] = "PERFORMANCE_TARGET_MISSED"
                    failed_case = (failed_browser.get("case") or {}).get("case_id")
                    if failed_case:
                        record["case_id"] = failed_case
                        for suffix, name in (("", "case"), ("/artifacts", "artifacts"), ("/messages", "messages")):
                            (output / (name + ".json")).write_text(json.dumps(http("/api/v1/agent-import-cases/" + failed_case + suffix), ensure_ascii=False, indent=2), encoding="utf-8")
                    raise RuntimeError("Normal browser submission failed")
            created = json.loads((output / "browser.json").read_text(encoding="utf-8"))["case"]
        else:
            created = http("/api/v1/agent-import-cases/from-path", {"source_path": str(source), "data_type": "BOTTOM_UP",
                "format_name": profile_name, "format_details": details, "delivery_policy": "auto_test"})
        record["case_id"] = created["case_id"]
        print(json.dumps({"created_case": created, "execution_policy": record["execution_policy"]}), flush=True)
        worker = None if args.normal_launcher else launch([sys.executable, "-B", Path(__file__).resolve(), "--worker-child"], "worker", env=env, cwd=workspace / "back", background=True)
        previous = None
        until = time.monotonic() + (3650 if args.source else 650)
        while worker is not None and worker.poll() is None:
            if time.monotonic() > until:
                raise TimeoutError("Normal-entry acceptance wall clock")
            state = http("/api/v1/agent-import-cases/" + created["case_id"])
            if state["status"] != previous:
                print(json.dumps({"status": state["status"]}), flush=True)
                previous = state["status"]
            time.sleep(1)
        from sqlalchemy import create_engine, text
        evidence_engine = create_engine(env["DATABASE_URL"])
        with evidence_engine.connect() as db:
            grant_counts = {table: db.execute(text("SELECT count(*) FROM " + table)).scalar() for table in
                ("agent_authorizations", "agent_import_policies", "agent_authorized_lineages", "agent_case_authority", "agent_experiments")}
            if any(grant_counts.values()):
                raise RuntimeError("Ordinary product acceptance must have no grant/binding records")
            record["grant_rows"] = grant_counts
        evidence_engine.dispose()
        state = http("/api/v1/agent-import-cases/" + created["case_id"])
        artifacts = http("/api/v1/agent-import-cases/" + created["case_id"] + "/artifacts")
        (output / "case.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "artifacts.json").write_text(json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
        record.update(case_status=state["status"], dataset_id=state["dataset_id"], candidate_sha256=state["candidate_zp_sha256"])
        if state["status"] == "SUCCESS":
            handover_bytes = http("/api/v1/agent-import-cases/" + created["case_id"] + "/handover", raw=True)
            (output / "HANDOVER.md").write_bytes(handover_bytes)
            if storage_id:
                with (temporary / "HANDOVER.md").open("xb") as handover_file:
                    handover_file.write(handover_bytes)
            record["status"] = "PASSED_REAL_NORMAL_ENTRY" if args.source else "PASSED_SYNTHETIC_NORMAL_ENTRY"
            if args.fixture_model:
                record["status"] = "PASSED_SYNTHETIC_TRANSPORT_PRODUCT_ENTRY"
            if args.browser_entry:
                with (output / "delivered-browser.log").open("w", encoding="utf-8") as browser_log:
                    completed = subprocess.run([str(args.node), str(root / "front/verification/product-import-check.mjs")],
                        input=canonical_bytes({"origin": origin, "mode": "delivery", "caseId": state["case_id"],
                            "real_source": bool(args.source),
                            "feedback": "Verify the published mapping using the independent maintenance role; this synthetic check changes no scientific facts." if args.fixture_model and not args.normal_launcher else None,
                            "output": str(output / "delivered-browser.json")}),
                        env=env, cwd=root / "front", stdout=browser_log, stderr=subprocess.STDOUT, timeout=90, **flags)
                if completed.returncode:
                    record["status"] = "FAILED"
                    raise RuntimeError("Final committed product browser failed")
            if args.fixture_model and not args.normal_launcher:
                launch([sys.executable, "-B", Path(__file__).resolve(), "--worker-child"], "maintenance-worker", env=env, cwd=workspace / "back")
                maintenance = http("/api/v1/agent-import-cases/" + state["case_id"] + "/maintenance")
                (output / "maintenance.json").write_text(json.dumps(maintenance, indent=2), encoding="utf-8")
                if len(maintenance) != 1 or maintenance[0]["state"] != "AWAITING_REVISION_VALIDATION":
                    record["status"] = "FAILED"
                    raise RuntimeError("Positive authorized maintenance consumption failed")
                launch([sys.executable, "-B", root / "cs/修订投影定向验收.py", "--case", state["case_id"],
                        "--output", output / "revision-pg.json"], "revision-pg", env=env, cwd=workspace / "back")
        else:
            raise RuntimeError("Normal-entry Case did not reach verified delivery")
    except Exception as exc:
        record["failure_type"] = type(exc).__name__
        raise
    finally:
        password_file.unlink(missing_ok=True)
        for process in reversed(processes):
            if process is not postgres and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        if postgres is not None:
            subprocess.run([str(args.postgres_bin / "pg_ctl.exe"), "-D", str(pgdata), "-m", "fast", "-w", "-t", "15", "stop"], env=base_env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, **flags)
        for lifetime in lifetimes:
            lifetime.close()
        for process in processes:
            process.wait(timeout=5)
        for log in logs:
            log.close()
        record["processes_stopped"] = all(p.poll() is not None for p in processes)
        if storage_id:
            allocated = 0
            stack = [temporary]
            while stack:
                with os.scandir(stack.pop()) as entries:
                    for entry in entries:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            allocated += info.st_size
            record["retained_file_bytes"] = allocated
        (output / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in record.items() if k != "commands"}), flush=True)


if __name__ == "__main__":
    main()
