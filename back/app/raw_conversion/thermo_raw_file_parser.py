"""ThermoRawFileParser subprocess adapter."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.raw_conversion.contracts import RawConversionRequest, RawConversionResult
from app.raw_conversion.errors import RawConversionError

CONVERTER_NAME = "ThermoRawFileParser"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_thermo_raw_file_parser_command(request: RawConversionRequest) -> list[str]:
    """Build the P0 ThermoRawFileParser command.

    ThermoRawFileParser CLI flags can vary by installed release. Keep the
    project convention centralized here so a future adjustment touches one
    function. P0 asks for uncompressed mzML output; validation below rejects
    gzip and missing embedded indexes after the process finishes.
    """
    if request.converter_exe is None:
        raise RawConversionError("raw_converter_missing", "THERMO_RAW_FILE_PARSER_EXE is not configured.")
    return [
        str(request.converter_exe),
        "-i",
        str(request.raw_path),
        "-o",
        str(request.output_dir),
        "-f",
        "1",
    ]


def locate_output_mzml(raw_path: Path, output_dir: Path) -> Path | None:
    for suffix in (".mzML", ".mzml"):
        candidate = output_dir / f"{raw_path.stem}{suffix}"
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def mzml_has_index_list_offset(path: Path, *, tail_bytes: int = 1024 * 1024) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(max(0, size - tail_bytes))
            return b"indexListOffset" in fh.read()
    except OSError:
        return False


def validate_converted_mzml(path: Path | None) -> Path:
    if path is None:
        raise RawConversionError("raw_conversion_output_missing", "Thermo RAW conversion did not produce an mzML file.")
    try:
        stat = path.stat()
    except OSError as exc:
        raise RawConversionError("raw_conversion_output_missing", f"Converted mzML does not exist: {path}") from exc
    if stat.st_size <= 0:
        raise RawConversionError("raw_conversion_output_invalid", f"Converted mzML is empty: {path}")
    if path.suffix.lower() != ".mzml":
        raise RawConversionError(
            "raw_conversion_output_invalid",
            f"Converted output is not an uncompressed mzML: {path}",
        )
    if not mzml_has_index_list_offset(path):
        raise RawConversionError(
            "raw_conversion_output_invalid",
            f"Converted mzML is missing embedded indexListOffset: {path}",
        )
    return path.resolve()


def run_thermo_raw_file_parser(
    request: RawConversionRequest,
    *,
    stdout_log_path: Path,
    stderr_log_path: Path,
) -> RawConversionResult:
    started_at = _now_iso()
    command: list[str] = []
    stdout_text = ""
    stderr_text = ""

    try:
        if request.converter_exe is None:
            raise RawConversionError("raw_converter_missing", "THERMO_RAW_FILE_PARSER_EXE is not configured.")
        if not request.converter_exe.is_file():
            raise RawConversionError(
                "raw_converter_missing",
                f"ThermoRawFileParser executable not found: {request.converter_exe}",
            )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_thermo_raw_file_parser_command(request)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            shell=False,
            check=False,
        )
        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""
        stdout_log_path.write_text(stdout_text, encoding="utf-8", errors="replace")
        stderr_log_path.write_text(stderr_text, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise RawConversionError(
                "raw_conversion_failed",
                f"ThermoRawFileParser exited with code {completed.returncode}; stderr log: {stderr_log_path}",
            )
        mzml_path = validate_converted_mzml(locate_output_mzml(request.raw_path, request.output_dir))
        return RawConversionResult(
            raw_path=request.raw_path.resolve(),
            mzml_path=mzml_path,
            status="converted",
            converter_name=CONVERTER_NAME,
            converter_version=None,
            command=command,
            started_at=started_at,
            finished_at=_now_iso(),
            stdout_log_path=stdout_log_path.resolve(),
            stderr_log_path=stderr_log_path.resolve(),
            error_message=None,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_text = str(exc.stdout or "")
        stderr_text = str(exc.stderr or "")
        stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_log_path.write_text(stdout_text, encoding="utf-8", errors="replace")
        stderr_log_path.write_text(stderr_text, encoding="utf-8", errors="replace")
        result = RawConversionResult(
            raw_path=request.raw_path.resolve(),
            mzml_path=None,
            status="failed",
            converter_name=CONVERTER_NAME,
            converter_version=None,
            command=command,
            started_at=started_at,
            finished_at=_now_iso(),
            stdout_log_path=stdout_log_path.resolve(),
            stderr_log_path=stderr_log_path.resolve(),
            error_message=f"Thermo RAW conversion timed out after {request.timeout_seconds}s.",
        )
        raise RawConversionError("raw_conversion_timeout", result.error_message, result=result) from exc
    except PermissionError as exc:
        result = RawConversionResult(
            raw_path=request.raw_path.resolve(),
            mzml_path=None,
            status="failed",
            converter_name=CONVERTER_NAME,
            converter_version=None,
            command=command,
            started_at=started_at,
            finished_at=_now_iso(),
            stdout_log_path=stdout_log_path.resolve(),
            stderr_log_path=stderr_log_path.resolve(),
            error_message=str(exc),
        )
        raise RawConversionError("raw_conversion_permission_denied", str(exc), result=result) from exc
    except RawConversionError as exc:
        if exc.result is not None:
            raise
        result = RawConversionResult(
            raw_path=request.raw_path.resolve(),
            mzml_path=locate_output_mzml(request.raw_path, request.output_dir),
            status="failed",
            converter_name=CONVERTER_NAME,
            converter_version=None,
            command=command,
            started_at=started_at,
            finished_at=_now_iso(),
            stdout_log_path=stdout_log_path.resolve() if stdout_log_path.exists() else None,
            stderr_log_path=stderr_log_path.resolve() if stderr_log_path.exists() else None,
            error_message=exc.message,
        )
        raise RawConversionError(exc.code, exc.message, result=result) from exc
