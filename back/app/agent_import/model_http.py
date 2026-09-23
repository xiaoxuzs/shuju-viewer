"""Terminating HTTP boundary for Worker model requests; keys travel through stdin.

The child is a fixed trusted helper, not generated code and not a code sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError

from app.agent_import.execution_control import checkpoint, report_progress
from app.agent_import.validation_processes import ProcessLifetime
from app.agent_import.model_audit import before_request, after_request


def request_model_json(url: str, *, method: str, api_key: str, body: dict | None, timeout: float, role: str = "model") -> dict:
    record, timeout = before_request(url, body, timeout, role)
    started = time.monotonic()
    encoded = json.dumps({"url": url, "method": method, "api_key": api_key, "body": body, "timeout": timeout}).encode("utf-8")
    response = None
    error = None
    try:
        # A cancelled progress checkpoint must settle its PREPARED reservation
        # as NOT_SENT, rather than escape before the request's finally block.
        report_progress("model:" + record["phase"])
        if record.get("task_request_id"):
            from .task_runtime import current_task
            current_task().mark_sending(record["task_request_id"])
        if record.get("authorization_request_id"):
            from .authorization_ledger import current_authority
            current_authority()[0].mark_sending(record["authorization_request_id"])
        response = _bounded_child(encoded, timeout=timeout)
        return response
    except Exception as exc:
        error = exc
        raise
    finally:
        after_request(record, response=response, error=error, elapsed=time.monotonic() - started)


def _bounded_child(encoded: bytes, *, timeout: float) -> dict:
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATHEXT") if name in os.environ}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    lifetime = ProcessLifetime()
    process = subprocess.Popen([sys.executable, "-B", "-m", "app.agent_import.model_http_worker"],
                               cwd=Path(__file__).resolve().parents[2], env=env, shell=False,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags)
    deadline = time.monotonic() + checkpoint(timeout=timeout)
    partial_timings = None
    try:
        lifetime.attach(process)
        first = True
        while True:
            remaining = min(deadline - time.monotonic(), checkpoint(timeout=timeout))
            if remaining <= 0:
                failure = TimeoutError("Model HTTP wall-clock deadline exceeded")
                failure.transport_timings = partial_timings
                raise failure
            try:
                stdout, _stderr = process.communicate(input=encoded if first else None, timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired as exc:
                first = False
                if exc.stderr:
                    try:
                        partial_timings = json.loads(exc.stderr.splitlines()[-1])
                    except (ValueError, IndexError):
                        pass
        checkpoint()
        if process.returncode != 0 or len(stdout) > 16 * 1024 * 1024:
            raise RuntimeError("Model HTTP worker failed or exceeded its response budget")
        envelope = json.loads(stdout)
        partial_timings = envelope.get("transport_timings") or partial_timings
        if envelope.get("http_status") is not None:
            raise HTTPError("<configured-model-endpoint>", int(envelope["http_status"]), "Model endpoint HTTP error", {}, None)
        if "error" in envelope:
            if envelope["error"] == "TimeoutError":
                raise TimeoutError("Model HTTP request timed out")
            raise OSError("Model HTTP request failed: " + envelope["error"])
        value = envelope.get("response")
        if not isinstance(value, dict):
            raise RuntimeError("Model response is not a JSON object")
        return value
    except BaseException as exc:
        # On Windows TimeoutExpired does not expose a reader thread's partial stderr.
        # Terminate first, then drain the owned pipes before classifying where it stalled.
        lifetime.close()
        if process.poll() is None:
            process.kill()
        try:
            _stdout, stderr = process.communicate(timeout=5)
            for line in stderr.splitlines():
                try:
                    partial_timings = json.loads(line)
                except ValueError:
                    continue
            exc.transport_timings = partial_timings
            exc.transport_capture_complete = True
        except (subprocess.TimeoutExpired, OSError):
            exc.transport_capture_complete = False
        raise
    finally:
        lifetime.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
