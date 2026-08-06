"""Small process registry for cancellable ZP worker subprocesses."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time


_LOCK = threading.Lock()
_PROCESSES: dict[str, subprocess.Popen[str]] = {}


def popen_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def register_process(job_id: str, process: subprocess.Popen[str]) -> None:
    with _LOCK:
        _PROCESSES[job_id] = process


def unregister_process(job_id: str, process: subprocess.Popen[str] | None = None) -> None:
    with _LOCK:
        current = _PROCESSES.get(job_id)
        if process is None or current is process:
            _PROCESSES.pop(job_id, None)


def terminate_registered(job_id: str, *, grace_seconds: float = 5.0) -> bool:
    with _LOCK:
        process = _PROCESSES.pop(job_id, None)
    if process is None:
        return False
    terminate_process_tree(process, grace_seconds=grace_seconds)
    return True


def terminate_process_tree(process: subprocess.Popen[str], *, grace_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        _terminate_windows(process, grace_seconds=grace_seconds)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    _wait_then_kill(process, grace_seconds=grace_seconds)


def _terminate_windows(process: subprocess.Popen[str], *, grace_seconds: float) -> None:
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
    except (OSError, ValueError):
        process.terminate()
    if _wait(process, grace_seconds):
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        check=False,
        capture_output=True,
        text=True,
    )


def _wait_then_kill(process: subprocess.Popen[str], *, grace_seconds: float) -> None:
    if _wait(process, grace_seconds):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()


def _wait(process: subprocess.Popen[str], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.05)
    return process.poll() is not None
