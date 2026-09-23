"""Pinned, credential-free Docker adapter; never falls back to host code execution.

Not enabled in API/graph. An operator must supply a tested isolation admission
callback from the trusted control plane. Exit zero is execution evidence only,
never an acceptance receipt or authority to register capability/publication.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

from app.agent_import.errors import AgentImportError
from app.agent_import.execution_control import checkpoint, current_fence
from app.agent_import.source_code import SourceSnapshot, _linked


@dataclass(frozen=True)
class DockerPolicy:
    executable: Path
    engine: str
    image: str
    seconds: int = 120
    memory_mb: int = 1024
    cpus: int = 1

    def __post_init__(self):
        if not self.executable.is_absolute() or not self.executable.is_file():
            raise ValueError("An explicit installed Docker executable is required")
        if not re.fullmatch(r"(?:unix:///[^\s]+|npipe:////\./pipe/[A-Za-z0-9_-]+)", self.engine):
            raise ValueError("Only explicitly authorized local engine sockets are admitted")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise ValueError("Use a locally installed immutable image ID; no registry pulls")
        if not 1 <= self.seconds <= 600 or not 256 <= self.memory_mb <= 4096 or not 1 <= self.cpus <= 2:
            raise ValueError("Sandbox resource policy out of bounds")


_COMMANDS = {
    "backend_tests": ["python", "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q", "back/tests"],
    "frontend_build": ["npm", "--prefix", "front", "run", "build"],
}


class DockerSandboxRunner:
    def __init__(self, policy: DockerPolicy, *, admission: Callable[[DockerPolicy], str] | None = None):
        self.policy = policy
        self._admission = admission

    def require_admission(self):
        if current_fence() is None or self._admission is None:
            raise AgentImportError("SANDBOX_NOT_ADMITTED", "Verified isolation is required before requesting generated code", status_code=403)
        identity = self._admission(self.policy)
        if not re.fullmatch(r"[0-9a-f]{64}", identity or ""):
            raise AgentImportError("SANDBOX_NOT_ADMITTED", "Invalid isolation admission", status_code=403)
        return identity

    def command(self, candidate: Path, name: str, check: str):
        if check not in _COMMANDS or not re.fullmatch(r"viewer-engineering-[0-9a-f]{32}", name):
            raise ValueError("Only fixed checks and operation-derived container names are allowed")
        candidate = candidate.absolute()
        if not candidate.is_dir() or any(_linked(p) for p in (candidate, *candidate.parents)) or "," in str(candidate):
            raise ValueError("Candidate mount must be a real, nonlinked isolated directory")
        return [str(self.policy.executable), "--host", self.policy.engine, "run", "--pull=never", "--name", name,
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--user=65534:65534", "--pids-limit=128", f"--memory={self.policy.memory_mb}m", f"--memory-swap={self.policy.memory_mb}m",
                f"--cpus={self.policy.cpus}", "--ipc=none", "--tmpfs=/tmp:rw,nosuid,nodev,size=128m",
                "--tmpfs=/work:rw,nosuid,nodev,size=512m", "--mount", f"type=bind,src={candidate},dst=/source,readonly",
                "--workdir=/work", "--env=HOME=/tmp", "--env=PYTHONDONTWRITEBYTECODE=1",
                "--entrypoint=python3", self.policy.image, "/opt/viewer/engineering-entry.py", check]

    def run(self, snapshot: SourceSnapshot, destination: Path, *, operation_key: str, check: str):
        if current_fence() is None or self._admission is None:
            raise AgentImportError("SANDBOX_NOT_ADMITTED", "A trusted Worker fence and actual isolation admission are required; no host fallback.", status_code=403)
        checkpoint()
        admission_id = self._admission(self.policy)
        if not re.fullmatch(r"[0-9a-f]{64}", admission_id or ""):
            raise AgentImportError("SANDBOX_NOT_ADMITTED", "No verified isolation record", status_code=403)
        if not re.fullmatch(r"[0-9a-f]{64}", operation_key):
            raise ValueError("Invalid operation key")
        # New path required: uncertain prior execution requires reconciliation, never overwrite/re-run.
        snapshot.export(destination)
        name = "viewer-engineering-" + operation_key[:32]
        command = self.command(destination, name, check)
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        started = time.monotonic()
        log = destination.parent / (name + ".log")
        cleanup_code = None
        try:
            with log.open("xb") as stream:
                process = subprocess.Popen(command, cwd=destination, env=env, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT, shell=False, **flags)
                try:
                    while process.poll() is None:
                        checkpoint()
                        if time.monotonic() - started >= self.policy.seconds:
                            raise TimeoutError("Engineering sandbox wall-clock deadline")
                        if stream.tell() > 4 * 1024 * 1024:
                            raise RuntimeError("Engineering log quota exceeded")
                        time.sleep(0.1)
                    checkpoint()
                    code = process.returncode
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
        finally:
            # Exact owned operation name only; the candidate never receives the engine socket.
            cleanup = subprocess.run([str(self.policy.executable), "--host", self.policy.engine, "rm", "-f", name],
                                     env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     timeout=15, shell=False, **flags)
            cleanup_code = cleanup.returncode
        if cleanup_code != 0:
            raise AgentImportError("SANDBOX_RECONCILIATION_REQUIRED", "Container cleanup not confirmed; do not repeat the operation", status_code=409)
        return {"status": "EXECUTED_NOT_ACCEPTED", "exit_code": code, "command": command, "snapshot_sha256": snapshot.identity,
                "operation_key": operation_key, "isolation_admission": admission_id, "elapsed_seconds": time.monotonic() - started,
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(), "cleanup_confirmed": True}
