"""ZP worker runners.

Production conversion is a subprocess that imports viewer-two's public
``binary_layer`` API. The web process never parses or writes .zp bytes itself.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.zp_conversion import process_control


ProgressReporter = Callable[[str, float, str | None], None]


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    job_id: str
    source_path: Path
    partial_path: Path
    final_path: Path
    certificate_path: Path
    temp_dir: Path
    format_version: int
    timeout_seconds: int
    worker_threads: int
    converter_path: Path | None
    binary_layer_commit: str | None
    v3_array_compression: str


@dataclass(frozen=True, slots=True)
class WorkerResult:
    output_bytes: int
    output_sha256: str
    validation_mode: str
    validation_certificate_path: Path
    format_version: int
    viewer_two_version: str | None = None


class WorkerExecutionError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class ZpWorkerRunner(Protocol):
    def run(self, request: WorkerRequest, report_progress: ProgressReporter) -> WorkerResult: ...


class NotConfiguredWorkerRunner:
    def run(self, request: WorkerRequest, report_progress: ProgressReporter) -> WorkerResult:
        del request
        report_progress("failed", 0.0, "ZP worker is not configured")
        raise WorkerExecutionError("ZP_WORKER_NOT_CONFIGURED")


class SubprocessZpWorkerRunner:
    def run(self, request: WorkerRequest, report_progress: ProgressReporter) -> WorkerResult:
        worker_python = settings.resolved_zp_worker_python()
        if worker_python is None:
            raise WorkerExecutionError("ZP_WORKER_NOT_CONFIGURED")
        if not worker_python.is_file():
            raise WorkerExecutionError("ZP_WORKER_NOT_CONFIGURED")

        request.temp_dir.mkdir(parents=True, exist_ok=True)
        request_file = request.temp_dir / "worker-request.json"
        request_file.write_text(json.dumps(_request_payload(request), sort_keys=True), encoding="utf-8")
        report_progress("convert", 10.0, None)
        env = _worker_env()
        command = [str(worker_python), "-c", _WORKER_CODE, str(request_file)]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=env,
            **process_control.popen_kwargs(),
        )
        process_control.register_process(request.job_id, process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process_control.terminate_process_tree(process)
                raise WorkerExecutionError("ZP_WORKER_TIMEOUT") from exc
        finally:
            process_control.unregister_process(request.job_id, process)

        payload = _parse_worker_payload(stdout)
        if process.returncode != 0:
            code = str(payload.get("code") or "ZP_WORKER_FAILED") if payload else "ZP_WORKER_FAILED"
            raise WorkerExecutionError(code)
        if not payload or payload.get("ok") is not True:
            raise WorkerExecutionError("ZP_WORKER_INVALID_RESULT")
        del stderr
        report_progress("commit", 95.0, None)
        try:
            return WorkerResult(
                output_bytes=int(payload["output_bytes"]),
                output_sha256=str(payload["output_sha256"]),
                validation_mode=str(payload.get("validation_mode") or "deep"),
                validation_certificate_path=Path(str(payload["validation_certificate_path"])),
                format_version=int(payload.get("format_version") or request.format_version),
                viewer_two_version=str(payload.get("viewer_two_version") or "unknown"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerExecutionError("ZP_WORKER_INVALID_RESULT") from exc


def default_worker_runner() -> ZpWorkerRunner:
    if settings.resolved_zp_worker_python() is None:
        return NotConfiguredWorkerRunner()
    return SubprocessZpWorkerRunner()


def _request_payload(request: WorkerRequest) -> dict[str, object]:
    return {
        "source_path": str(request.source_path),
        "partial_path": str(request.partial_path),
        "final_path": str(request.final_path),
        "certificate_path": str(request.certificate_path),
        "temp_dir": str(request.temp_dir),
        "format_version": request.format_version,
        "timeout_seconds": request.timeout_seconds,
        "worker_threads": request.worker_threads,
        "converter_path": str(request.converter_path) if request.converter_path is not None else None,
        "binary_layer_commit": request.binary_layer_commit,
        "v3_array_compression": request.v3_array_compression,
    }


def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    entries = settings.zp_worker_pythonpath_list
    if entries:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join(entries + ([existing] if existing else []))
    return env


def _parse_worker_payload(stdout: str) -> dict[str, object] | None:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


_WORKER_CODE = r'''
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finish(payload: dict[str, object], code: int = 0) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)
    raise SystemExit(code)


try:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    source = Path(request["source_path"])
    partial = Path(request["partial_path"])
    final = Path(request["final_path"])
    certificate = Path(request["certificate_path"])
    temp_dir = Path(request["temp_dir"])

    from binary_layer import ConversionOptions
    from binary_layer.service import convert_source_to_zp, validate_zp

    converter = request.get("converter_path")
    option_kwargs = {
        "converter_path": Path(converter) if converter else None,
        "temporary_directory": temp_dir / "intermediate",
        "keep_intermediate": False,
        "timeout_seconds": float(request["timeout_seconds"]),
    }
    option_fields = getattr(ConversionOptions, "__dataclass_fields__", {})
    if "worker_threads" in option_fields:
        option_kwargs["worker_threads"] = int(request["worker_threads"])
    if "v3_array_compression" in option_fields:
        option_kwargs["v3_array_compression"] = str(request.get("v3_array_compression") or "zstd")
    options = ConversionOptions(**option_kwargs)
    result = convert_source_to_zp(
        source,
        partial,
        format_version=int(request["format_version"]),
        options=options,
    )
    validation = validate_zp(partial, mode="deep", certificate_path=certificate)
    if not validation.valid:
        _finish({"ok": False, "code": "ZP_WORKER_FAILED"}, 2)
    if final.exists():
        _finish({"ok": False, "code": "ZP_FINAL_ALREADY_EXISTS"}, 3)
    try:
        os.link(partial, final)
        partial.unlink()
    except OSError:
        _finish({"ok": False, "code": "ZP_WORKER_FAILED"}, 4)
    output_sha256 = getattr(result, "output_sha256", None) or getattr(validation, "file_sha256", None) or _sha256(final)
    try:
        package_version = importlib.metadata.version("binary-layer")
    except importlib.metadata.PackageNotFoundError:
        package_version = str(request.get("binary_layer_commit") or "unknown")
    _finish(
        {
            "ok": True,
            "output_bytes": final.stat().st_size,
            "output_sha256": output_sha256,
            "validation_mode": "deep",
            "validation_certificate_path": str(certificate),
            "format_version": int(request["format_version"]),
            "viewer_two_version": str(request.get("binary_layer_commit") or package_version),
        }
    )
except BaseException as exc:  # noqa: BLE001
    code = getattr(exc, "code", None) or "ZP_WORKER_FAILED"
    _finish({"ok": False, "code": str(code)}, 1)
'''
