"""Real local PostgreSQL/HTTP/browser verification of TRUSTED Viewer code.

The launcher owns the cluster, ports and processes. This is deliberately not a
sandbox for model-generated patches. That separate gate remains fail-closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from typing import Literal
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_import.execution_control import checkpoint, report_progress
from app.agent_import.source_code import SourceSnapshot, canonical_bytes, digest_bytes
from app.agent_import.input_assets import hash_file
from app.agent_import.validation_processes import ProcessLifetime
from app.agent_import.verification_full import FullAcceptanceContract, VERIFIER_VERSION, EXTENDED_VERIFIER_VERSION


class MatchExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_record_id: str
    sequence: str
    rt_minutes: float | None
    q_value: float | None = None
    decoy: bool | None = None
    quantification_values: list[float | None] = Field(default_factory=list)
    quantification_units: list[str | None] = Field(default_factory=list)


class AcceptanceContract(BaseModel):
    """Trusted source oracle, kept outside candidate/model writable directories."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence: str = Field(min_length=10)
    total_matches: int = Field(ge=1, le=100)
    matches: list[MatchExpectation] = Field(min_length=1)
    scope: str = Field(min_length=5)
    requirements_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required_views: dict[str, Literal["AVAILABLE", "PARTIAL"]] = Field(default_factory=lambda: {"bu.matches": "AVAILABLE", "bu.peptides": "AVAILABLE"})

    @model_validator(mode="after")
    def require_complete_oracle(self):
        if len(self.matches) != self.total_matches or len({item.source_record_id for item in self.matches}) != self.total_matches:
            raise ValueError("This initial delivery verifier requires an independent oracle for every row (at most 100)")
        if any(len(item.quantification_values) != len(item.quantification_units) for item in self.matches):
            raise ValueError("Every quantified value requires an explicit expected unit, including null")
        return self


def load_acceptance_contract(raw: str):
    value = json.loads(raw)
    if value.get("schema_version", 1) not in {1, 2, 3}:
        raise ValueError("Unsupported acceptance contract version")
    return FullAcceptanceContract.model_validate(value) if value.get("schema_version", 1) >= 2 else AcceptanceContract.model_validate(value)


@dataclass(frozen=True)
class VerificationRuntime:
    source_root: Path
    postgres_bin: Path
    python: Path
    node: Path
    browser_cache: Path
    evidence_root: Path

    def __post_init__(self):
        # Child processes run inside the snapshot, not the caller's cwd.
        for name in ("source_root", "postgres_bin", "python", "node", "browser_cache", "evidence_root"):
            object.__setattr__(self, name, getattr(self, name).resolve())


def restricted_environment(temporary: Path, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    # Do not inherit DATABASE_URL, model keys, proxy credentials, NODE_OPTIONS,
    # PYTHONPATH, HOME, or dotenv. Dependencies are explicitly supplied by caller.
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT") if name in os.environ}
    env.update({"TEMP": str(temporary), "TMP": str(temporary), "TMPDIR": str(temporary),
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "NO_PROXY": "127.0.0.1,localhost"})
    env.update(extra or {})
    return env


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _json_http(url: str, body: dict | None = None, *, timeout: int = 10) -> dict:
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Verifier HTTP is restricted to its owned loopback application")
    from app.agent_import.model_http import _bounded_child
    # Fixed cancellable helper, NOT a model request or model-budget reservation.
    return _bounded_child(json.dumps({"url": url, "method": "POST" if body is not None else "GET", "api_key": "",
        "body": body, "timeout": timeout, "wrap_response": True}).encode("utf-8"), timeout=checkpoint(timeout=timeout))["value"]


def seal_record(record: dict, signing_key: bytes) -> dict:
    if len(signing_key) < 32:
        raise ValueError("Verification signing key must have at least 32 bytes")
    return {"record": record, "signature": hmac.new(signing_key, canonical_bytes(record), hashlib.sha256).hexdigest()}


def verify_receipt(receipt: dict, signing_key: bytes, *, code_sha256: str, candidate_sha256: str, source_sha256: str) -> None:
    record = receipt["record"]
    expected = seal_record(record, signing_key)["signature"]
    if not hmac.compare_digest(expected, str(receipt.get("signature", ""))):
        raise ValueError("Verification receipt signature is invalid")
    if record.get("status") != "PASSED" or (
        record.get("code_sha256"), record.get("candidate_sha256"), record.get("source_sha256")
    ) != (code_sha256, candidate_sha256, source_sha256):
        raise ValueError("Verification evidence is stale, incomplete or failed")
    if not record.get("browser_assertions") or not record.get("import_result"):
        raise ValueError("Real import and browser evidence are required")
    if not record.get("cleanup", {}).get("processes_stopped"):
        raise ValueError("Validation process cleanup was not verified")
    if record.get("verifier_version") in {VERIFIER_VERSION, EXTENDED_VERIFIER_VERSION}:
        full = record.get("full_verification", {})
        if full.get("status") != "PASSED" or any(name not in full.get("coverage", {}) for name in ("source", "semantic", "spectra", "projection", "http")):
            raise ValueError("Full verification did not finish every required layer")


class CandidateVerifier:
    def __init__(self, runtime: VerificationRuntime, *, signing_key: bytes) -> None:
        if len(signing_key) < 32:
            raise ValueError("Verification signing key is required")
        self.runtime = runtime
        self.signing_key = signing_key

    def verify(self, candidate: Path, oracle: AcceptanceContract | FullAcceptanceContract, *, case_id: str, context_revision: int = 1, generated_code: bool = False, input_root: Path | None = None) -> dict:
        if generated_code:
            raise ValueError("Generated-code execution requires a separately verified sandbox; host fallback is forbidden")
        cfg = self.runtime
        full_scope = isinstance(oracle, FullAcceptanceContract)
        if full_scope and input_root is None:
            raise ValueError("Full-source verification requires the retained input directory")
        snapshot = SourceSnapshot.capture(cfg.source_root)
        candidate_hash = hash_file(candidate)
        operation_key = digest_bytes(canonical_bytes([case_id, context_revision, snapshot.identity, candidate_hash, oracle.model_dump(mode="json")]))
        cfg.evidence_root.mkdir(parents=True, exist_ok=True)
        evidence = cfg.evidence_root / operation_key
        if evidence.exists():
            from app.agent_import.errors import AgentImportError
            try:
                previous = json.loads((evidence / "receipt.json").read_text(encoding="utf-8"))
                verify_receipt(previous, self.signing_key, code_sha256=snapshot.identity,
                               candidate_sha256=candidate_hash, source_sha256=oracle.source_identity)
                record = previous["record"]
                if full_scope and (record.get("verifier_version") != oracle.verifier_version or hash_file(evidence / "full-verification.json") != record.get("full_verification_sha256")):
                    raise ValueError("Missing or changed full-scope verification evidence")
                if record["case_id"] != case_id or record["context_revision"] != context_revision:
                    raise ValueError("Case context changed")
                if hash_file(evidence / "browser.json") != record["browser_artifact_sha256"] or hash_file(evidence / "browser-trace.zip") != record["trace_sha256"]:
                    raise ValueError("Retained verification evidence changed")
                return {**previous, "reused_existing_operation": operation_key}
            except (ValueError, KeyError, OSError) as exc:
                raise AgentImportError("VERIFICATION_RECONCILIATION_REQUIRED", "A prior verification operation is incomplete or failed. Its retained process/asset inventory must be reconciled before retrying.", status_code=409) from exc
        evidence.mkdir()  # collision is a reconciliation condition, never overwrite prior evidence
        run_root = Path(tempfile.mkdtemp(prefix="viewer-validation-"))
        workspace = run_root / "source"
        snapshot.export(workspace)
        data = run_root / "data"
        data.mkdir()
        assets = data / "assets"
        assets.mkdir()
        incoming = assets / "candidate.zp"
        shutil.copyfile(candidate, incoming)
        if hash_file(incoming) != candidate_hash:
            raise ValueError("Candidate changed while creating validation input")
        pg_port, api_port, front_port = _port(), _port(), _port()
        if len({pg_port, api_port, front_port}) != 3:
            raise ValueError("Candidate ports collided")
        processes: list[subprocess.Popen] = []
        handles = []
        lifetimes = []
        commands = []
        record = {"schema_version": 1, "operation_key": operation_key, "case_id": case_id, "context_revision": context_revision,
                  "code_sha256": snapshot.identity, "candidate_sha256": candidate_hash,
                  "source_sha256": oracle.source_identity, "oracle_sha256": digest_bytes(canonical_bytes(oracle.model_dump(mode="json"))),
                  "scope": oracle.scope, "source_evidence": oracle.source_evidence,
                  "status": "FAILED", "commands": commands, "browser_assertions": [],
                  "cleanup": {"temporary_root": str(run_root), "processes_stopped": False, "retained": ["source", "data", "postgres", "logs"]}}
        if full_scope:
            record["verifier_version"] = oracle.verifier_version
        safe_config = {"environment": "test", "worker": "disabled", "model_access": "disabled", "listen": "127.0.0.1",
                       "database": "new isolated PostgreSQL cluster", "assets": "private temporary DATA_ROOT",
                       "source_code": "trusted working-copy snapshot", "browser_recipe": "bottom-up-complete-oracle-v1"}
        record["configuration"] = safe_config
        record["configuration_sha256"] = digest_bytes(canonical_bytes(safe_config))
        (evidence / "source-manifest.json").write_bytes(canonical_bytes({"identity": snapshot.identity, "files": snapshot.manifest}))
        base_env = restricted_environment(run_root)
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}

        def command(args: list[str], label: str, *, env: dict | None = None, cwd: Path | None = None, background: bool = False):
            checkpoint()
            record["phase"] = label
            report_progress("verification:" + label)
            log = (evidence / f"{label}.log").open("w", encoding="utf-8")
            handles.append(log)
            entry = {"name": label, "argv": [str(arg) for arg in args], "cwd": str(cwd or run_root), "exit_code": None}
            commands.append(entry)
            process = subprocess.Popen([str(arg) for arg in args], cwd=cwd or run_root, env=env or base_env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False, **flags)
            processes.append(process)
            lifetime = ProcessLifetime()
            lifetimes.append(lifetime)
            lifetime.attach(process)
            entry["pid"] = process.pid
            if background:
                return process
            deadline = time.monotonic() + checkpoint(timeout=oracle.max_seconds if full_scope and label in {"staging", "full-verification", "committed-import"} else 180)
            last_progress = 0.0
            while process.poll() is None:
                checkpoint()
                if label == "full-verification" and time.monotonic() - last_progress > 2:
                    last_progress = time.monotonic()
                    try:
                        progress = json.loads((evidence / "full-progress.json").read_text(encoding="utf-8"))
                        report_progress("verification:" + str(progress["phase"]), progress.get("processed"), progress.get("total"))
                    except (OSError, ValueError, KeyError):
                        pass
                if time.monotonic() >= deadline:
                    process.kill()
                    raise TimeoutError(f"{label} exceeded the candidate command deadline")
                time.sleep(0.1)
            entry["exit_code"] = process.returncode
            if process.returncode != 0:
                raise RuntimeError(f"{label} failed; inspect its retained log")
            return process

        admin_password = secrets.token_urlsafe(32)
        app_password = secrets.token_urlsafe(32)
        password_file = run_root / "admin-password"
        password_file.write_text(admin_password, encoding="utf-8")
        pgdata = run_root / "postgres"
        pg_started = False
        try:
            command([cfg.postgres_bin / "initdb.exe" if os.name == "nt" else cfg.postgres_bin / "initdb",
                     "-D", pgdata, "-U", "validator_admin", "--auth=scram-sha-256", "--pwfile", password_file,
                     "--encoding=UTF8", "--no-locale"], "initdb")
            password_file.unlink()
            postgres = command([cfg.postgres_bin / ("postgres.exe" if os.name == "nt" else "postgres"),
                                "-D", pgdata, "-h", "127.0.0.1", "-p", str(pg_port),
                                "-c", "shared_buffers=32MB", "-c", "max_connections=32"], "postgres", background=True)
            pg_started = True
            import psycopg
            from psycopg import sql
            end = time.monotonic() + 30
            while True:
                checkpoint()
                try:
                    connection = psycopg.connect(host="127.0.0.1", port=pg_port, dbname="postgres", user="validator_admin",
                                                password=admin_password, connect_timeout=2, autocommit=True)
                    break
                except psycopg.OperationalError:
                    if postgres.poll() is not None or time.monotonic() >= end:
                        raise RuntimeError("Isolated PostgreSQL did not become ready") from None
                    time.sleep(0.2)
            with connection:
                actual = connection.execute("SHOW data_directory").fetchone()[0]
                if Path(actual).resolve() != pgdata.resolve():
                    raise RuntimeError("PostgreSQL cluster identity mismatch")
                connection.execute(sql.SQL("CREATE ROLE viewer_validation LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Literal(app_password)))
                connection.execute("CREATE DATABASE viewer_test_delivery OWNER viewer_validation")
                record["postgres_version"] = connection.execute("SHOW server_version").fetchone()[0]
            with psycopg.connect(host="127.0.0.1", port=pg_port, dbname="viewer_test_delivery", user="viewer_validation",
                                 password=app_password, connect_timeout=2) as database:
                database.execute((workspace / "docs/universal_schema.sql").read_text(encoding="utf-8"))
                role = database.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
                if any(role):
                    raise RuntimeError("Candidate database role is not restricted")
            api_env = restricted_environment(run_root, extra={
                "VIEWER_ENV": "test", "DATABASE_URL": f"postgresql+psycopg://viewer_validation:{app_password}@127.0.0.1:{pg_port}/viewer_test_delivery",
                "DATA_ROOT": str(data), "VIEWER_BUILD_ID": snapshot.identity,
                "VIEWER_VALIDATION_ID": operation_key,
                "AGENT_IMPORT_ENABLED": "false", "AGENT_API_WORKER_ENABLED": "false",
                "IMPORT_NATIVE_FOLDER_PICKER": "false", "IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT": "true",
                "BU_FRAGMENT_MATCH_ROOT": str(data / "pfmb"), "BU_UNIPROT_ENABLED": "false",
                "API_CORS_ORIGINS": f"http://127.0.0.1:{front_port}",
                "PGOPTIONS": "-c lock_timeout=15000 -c statement_timeout=120000",
                "VIEWER_TEST_TRACE_SECONDS": "60",
            })
            api = command([cfg.python, "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                          "backend", env=api_env, cwd=workspace / "back", background=True)
            api_url = f"http://127.0.0.1:{api_port}"
            self._wait_health(api_url, api, snapshot.identity, operation_key)
            command([cfg.python, "-B", "-m", "app.agent_import.validation_stage", "--candidate", incoming,
                     "--output", evidence / "staging.json"], "staging", env=api_env, cwd=workspace / "back")
            record["staging_result"] = json.loads((evidence / "staging.json").read_text(encoding="utf-8"))
            record["phase"] = "external_staging_probe"
            externally_visible = _json_http(api_url + "/api/v1/datasets")
            if externally_visible != []:
                raise RuntimeError("Staging rows became visible outside their transaction")
            record["staging_external_visibility"] = "none"
            record["phase"] = "import_http"
            report_progress("verification:actual_import")
            if full_scope:
                command([cfg.python, "-B", "-m", "app.agent_import.validation_import", "--candidate", incoming,
                    "--output", evidence / "committed-import.json"], "committed-import", env=api_env, cwd=workspace / "back")
                committed = json.loads((evidence / "committed-import.json").read_text(encoding="utf-8"))
                imported = committed["import_result"]
                record["committed_import_metrics"] = {k: v for k, v in committed.items() if k != "import_result"}
            else:
                imported = _json_http(api_url + "/api/v1/agent-zp/imports", {
                "source_path": str(incoming), "slug": "candidate-validation", "name": "Candidate validation",
                "analysis_category": "BOTTOM_UP", "source_profile": "verified-candidate",
                "binary_operation": "register_existing_zp", "format_version": 3, "replace_existing": False,
                }, timeout=10)
            record["import_result"] = imported
            report = _json_http(api_url + "/api/v1/datasets/candidate-validation/capability-report")
            if report.get("enforcement") != "ENFORCED" or report.get("provenance") != "VALIDATED_FACTS":
                raise RuntimeError("Automatic evidence cannot upgrade an advisory legacy capability report")
            views = {item["view_id"]: item["availability"] for item in report["views"]}
            for view_id, minimum in oracle.required_views.items():
                allowed = {"AVAILABLE"} if minimum == "AVAILABLE" else {"AVAILABLE", "PARTIAL"}
                if views.get(view_id) not in allowed:
                    raise RuntimeError("A required view is unavailable; silent delivery downgrade is forbidden")
            record["capability_report"] = report
            record["candidate_database_id"] = imported["dataset_id"]
            browser_oracle = oracle.model_dump(mode="json")
            if full_scope:
                oracle_file = run_root / "full-oracle.json"
                oracle_file.write_text(oracle.model_dump_json(), encoding="utf-8")
                command([cfg.python, "-B", "-m", "app.agent_import.verification_full_stage", "--candidate", incoming,
                         "--input-root", input_root.resolve(), "--oracle", oracle_file, "--output", evidence / "full-verification.json",
                         "--api-url", api_url, "--slug", "candidate-validation"], "full-verification", env=api_env, cwd=workspace / "back")
                full = json.loads((evidence / "full-verification.json").read_text(encoding="utf-8"))
                if full.get("status") != "PASSED":
                    raise ValueError("Full-source reconciliation was not completed")
                record["full_verification"] = full
                record["full_verification_sha256"] = hash_file(evidence / "full-verification.json")
                browser_oracle = full["browser_oracle"]
            browser_input = {"base_url": f"http://127.0.0.1:{front_port}", "api_url": api_url,
                             "validation_id": operation_key,
                             "build_id": snapshot.identity, "oracle": browser_oracle,
                             "output": str(evidence / "browser.json"), "trace": str(evidence / "browser-trace.zip")}
            (run_root / "browser-input.json").write_bytes(canonical_bytes(browser_input))
            # Trusted Vite runner uses this explicit dependency installation; no install and no old dist.
            frontend = command([cfg.node, cfg.source_root / "front/verification/candidate-server.mjs", workspace / "front",
                                str(front_port), str(api_port), snapshot.identity, operation_key], "frontend",
                               env=restricted_environment(run_root), cwd=workspace / "front", background=True)
            self._wait_http(f"http://127.0.0.1:{front_port}", frontend)
            command([cfg.node, cfg.source_root / "front/verification/browser-check.mjs", run_root / "browser-input.json"],
                    "browser", env=restricted_environment(run_root, extra={"PLAYWRIGHT_BROWSERS_PATH": str(cfg.browser_cache)}))
            browser = json.loads((evidence / "browser.json").read_text(encoding="utf-8"))
            if browser.get("passed") is not True or not browser.get("assertions"):
                raise RuntimeError("Browser did not produce verified assertions")
            record["browser_assertions"] = browser["assertions"]
            record["browser_artifact_sha256"] = hash_file(evidence / "browser.json")
            record["trace_sha256"] = hash_file(evidence / "browser-trace.zip")
            if hash_file(candidate) != candidate_hash or SourceSnapshot.capture(cfg.source_root).identity != snapshot.identity:
                raise RuntimeError("Source code or candidate changed during verification")
            record["status"] = "PASSED"
        except Exception as exc:
            # Do not put DSNs, SQL parameters or model credentials in public evidence.
            record["failure_type"] = type(exc).__name__
            record["failure_stage"] = record.get("phase", "snapshot")
            raise
        finally:
            password_file.unlink(missing_ok=True)
            for process in reversed(processes):
                if process.poll() is None and (not pg_started or process is not postgres):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            if pg_started:
                pgctl = cfg.postgres_bin / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
                subprocess.run([str(pgctl), "-D", str(pgdata), "-m", "fast", "-w", "-t", "15", "stop"],
                               env=base_env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=20, **flags)
                postgres.wait(timeout=5)
            for entry, process in zip(commands, processes):
                entry["exit_code"] = process.poll()
            for lifetime in lifetimes:
                lifetime.close()
            for handle in handles:
                handle.close()
            record["cleanup"]["processes_stopped"] = all(process.poll() is not None for process in processes)
            for port in (api_port, front_port, pg_port):
                with socket.socket() as probe:
                    probe.settimeout(0.5)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        record["cleanup"]["processes_stopped"] = False
                        record["status"] = "FAILED"
                        record["failure_type"] = "CandidateProcessCleanupIncomplete"
            # Retain this exact inventory for operator cleanup; never delete unknown paths.
            receipt = seal_record(record, self.signing_key)
            (evidence / "receipt.json").write_bytes(canonical_bytes(receipt))
        return receipt

    @staticmethod
    def _wait_http(url: str, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            checkpoint()
            if process.poll() is not None:
                break
            try:
                with urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError("Candidate HTTP process did not become ready")

    @classmethod
    def _wait_health(cls, base_url: str, process: subprocess.Popen, identity: str, operation: str) -> None:
        cls._wait_http(base_url + "/health", process)
        health = _json_http(base_url + "/health")
        if health.get("build_id") != identity or health.get("validation_id") != operation:
            raise RuntimeError("Candidate API build identity mismatch")
