"""Trusted, expiring isolation admission. Candidate self-tests cannot issue it."""
from dataclasses import asdict
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from .errors import AgentImportError
from .source_code import canonical_bytes

CHECKS = frozenset({"non_root", "source_read_only", "root_read_only", "network_denied", "no_control_socket", "no_secrets", "private_work", "memory_limit", "pid_limit"})


def policy_identity(policy):
    value = asdict(policy)
    value["executable"] = str(policy.executable.resolve(strict=True))
    value["executable_sha256"] = hashlib.sha256(policy.executable.read_bytes()).hexdigest()
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def seal_admission(policy, observations, key, *, now=None):
    """Called only by trusted probe controller, never by a candidate callback."""
    if len(key) < 32 or set(observations) != CHECKS or any(v is not True for v in observations.values()):
        raise ValueError("All registered isolation probes must pass; no boolean-only admission")
    now = time.time() if now is None else now
    record = {"schema_version": 1, "policy_sha256": policy_identity(policy), "image": policy.image,
        "issued_at": now, "expires_at": now + 900, "checks": observations,
        "scope": "fixed offline Linux engineering tests only; no database/network/browser admission"}
    return {"record": record, "signature": hmac.new(key, canonical_bytes(record), hashlib.sha256).hexdigest()}


def verify_admission(receipt, policy, key, *, now=None):
    now = time.time() if now is None else now
    record = receipt.get("record", {})
    valid = len(key) >= 32 and hmac.compare_digest(receipt.get("signature", ""), hmac.new(key, canonical_bytes(record), hashlib.sha256).hexdigest())
    if not valid or record.get("schema_version") != 1 or record.get("policy_sha256") != policy_identity(policy) or record.get("image") != policy.image:
        raise AgentImportError("SANDBOX_NOT_ADMITTED", "Sandbox policy/image/admission identity differs", status_code=403)
    if not record.get("issued_at", now + 1) <= now < record.get("expires_at", 0) or set(record.get("checks", {})) != CHECKS or not all(v is True for v in record["checks"].values()):
        raise AgentImportError("SANDBOX_NOT_ADMITTED", "Sandbox admission expired or incomplete", status_code=403)
    return hashlib.sha256(canonical_bytes(receipt)).hexdigest()


def run_isolation_probes(policy, key):
    """Requires an installed pinned image containing the trusted probe script.

    No pulls/installs or remote engine. This does not admit integration networks,
    browsers or model-generated code execution on the host.
    """
    import os
    from .sandbox_runner import DockerSandboxRunner
    nonce = secrets.token_hex(16)
    name = "viewer-engineering-" + nonce
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with tempfile.TemporaryDirectory(prefix="viewer-admission-probe-") as directory:
        mount = Path(directory)
        (mount / "probe.txt").write_text(nonce, encoding="ascii")
        command = DockerSandboxRunner(policy).command(mount, name, "backend_tests")
        command[-2:] = ["/opt/viewer/engineering-admission.py", nonce]
        try:
            result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=min(policy.seconds, 30), shell=False, **flags)
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError("Isolation probes failed; no admission issued")
            evidence = json.loads(result.stdout)
            if evidence.get("nonce") != nonce:
                raise ValueError("Isolation probe challenge mismatch")
        finally:
            cleanup = subprocess.run([str(policy.executable), "--host", policy.engine, "rm", "-f", name], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, shell=False, **flags)
            if cleanup.returncode:
                raise ValueError("Probe container cleanup unconfirmed; admission denied")
    return seal_admission(policy, evidence["checks"], key)


def configured_runner():
    from app.core.config import settings
    from .sandbox_runner import DockerPolicy, DockerSandboxRunner
    fields = (settings.agent_engineering_executable, settings.agent_engineering_engine, settings.agent_engineering_image,
              settings.agent_engineering_admission_path, settings.agent_engineering_admission_key)
    if not settings.agent_engineering_enabled or not all(fields):
        return None
    policy = DockerPolicy(executable=settings.agent_engineering_executable, engine=settings.agent_engineering_engine, image=settings.agent_engineering_image)
    def admission(actual_policy):
        receipt = json.loads(settings.agent_engineering_admission_path.read_text(encoding="utf-8"))
        return verify_admission(receipt, actual_policy, settings.agent_engineering_admission_key.encode())
    return DockerSandboxRunner(policy, admission=admission)
