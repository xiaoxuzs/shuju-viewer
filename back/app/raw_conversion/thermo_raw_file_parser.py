"""ThermoRawFileParser subprocess adapter."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.raw_conversion.contracts import RawConversionRequest, RawConversionResult
from app.raw_conversion.errors import RawConversionError

CONVERTER_NAME = "ThermoRawFileParser"
INDEX_LIST_OFFSET_MARKER = b"indexListOffset"
INDEXED_MZML_OPEN_MARKER = b"<indexedmzML"
INDEXED_MZML_CLOSE_MARKER = b"</indexedmzML>"
EMBEDDED_INDEX_MARKERS = (
    INDEX_LIST_OFFSET_MARKER,
    INDEXED_MZML_OPEN_MARKER,
    INDEXED_MZML_CLOSE_MARKER,
)
DEFAULT_TAIL_BYTES = 4 * 1024 * 1024
DEFAULT_SCAN_CHUNK_BYTES = 1024 * 1024
_OutputSignature = tuple[int, int, int | None]
_OutputSnapshot = dict[Path, _OutputSignature]


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
        f"-i={request.raw_path}",
        f"-o={request.output_dir}",
        "-f=2",
        "-m=0",
    ]


def _output_mzml_candidates(raw_path: Path, output_dir: Path) -> tuple[Path, ...]:
    return tuple(output_dir / f"{raw_path.stem}{suffix}" for suffix in (".mzML", ".mzml", ".mzML.gz", ".mzml.gz"))


def _output_signature(candidate: Path) -> _OutputSignature | None:
    try:
        stat = candidate.stat()
        if not candidate.is_file():
            return None
    except OSError:
        return None
    inode = stat.st_ino or None
    return stat.st_size, stat.st_mtime_ns, inode


def _snapshot_output_mzml(raw_path: Path, output_dir: Path) -> _OutputSnapshot:
    snapshot: _OutputSnapshot = {}
    for candidate in _output_mzml_candidates(raw_path, output_dir):
        signature = _output_signature(candidate)
        if signature is not None:
            snapshot[candidate] = signature
    return snapshot


def _output_changed(previous: _OutputSignature, current: _OutputSignature) -> bool:
    if current[:2] != previous[:2]:
        return True
    previous_inode = previous[2]
    current_inode = current[2]
    return previous_inode is not None and current_inode is not None and current_inode != previous_inode


def _locate_changed_output_mzml(
    raw_path: Path,
    output_dir: Path,
    *,
    previous_snapshot: _OutputSnapshot,
) -> Path | None:
    for candidate in _output_mzml_candidates(raw_path, output_dir):
        current = _output_signature(candidate)
        if current is None:
            continue
        previous = previous_snapshot.get(candidate)
        if previous is None or _output_changed(previous, current):
            return candidate.resolve()
    return None


def locate_output_mzml(raw_path: Path, output_dir: Path, *, modified_since_ns: int | None = None) -> Path | None:
    for candidate in _output_mzml_candidates(raw_path, output_dir):
        signature = _output_signature(candidate)
        if signature is not None and (modified_since_ns is None or signature[1] >= modified_since_ns):
            return candidate.resolve()
    return None


def _find_embedded_index_markers(data: bytes) -> set[bytes]:
    return {marker for marker in EMBEDDED_INDEX_MARKERS if marker in data}


def has_embedded_index_list_offset(
    path: Path,
    *,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
    chunk_bytes: int = DEFAULT_SCAN_CHUNK_BYTES,
) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            tail_start = max(0, size - tail_bytes)
            fh.seek(tail_start)
            if INDEX_LIST_OFFSET_MARKER in _find_embedded_index_markers(fh.read()):
                return True
            if tail_start == 0:
                return False

            fh.seek(0)
            overlap = b""
            overlap_size = max(len(marker) for marker in EMBEDDED_INDEX_MARKERS) - 1
            while True:
                chunk = fh.read(chunk_bytes)
                if not chunk:
                    return False
                data = overlap + chunk
                if INDEX_LIST_OFFSET_MARKER in _find_embedded_index_markers(data):
                    return True
                overlap = data[-overlap_size:]
    except OSError:
        return False


def _format_validation_context(
    *,
    command: list[str] | None,
    output_path: Path | None,
    file_size: int | None,
    stdout_log_path: Path | None,
    stderr_log_path: Path | None,
) -> str:
    parts = [
        f"command: {command or []}",
        f"output path: {output_path}",
        f"file size: {file_size if file_size is not None else 'unknown'}",
        f"searched marker: {INDEX_LIST_OFFSET_MARKER.decode('ascii')}",
    ]
    if stdout_log_path is not None:
        parts.append(f"stdout log: {stdout_log_path}")
    if stderr_log_path is not None:
        parts.append(f"stderr log: {stderr_log_path}")
    return "; ".join(parts)


def validate_converted_mzml(
    path: Path | None,
    *,
    command: list[str] | None = None,
    stdout_log_path: Path | None = None,
    stderr_log_path: Path | None = None,
    expected_output_path: Path | None = None,
    invalid_subject: str = "Converted mzML",
) -> Path:
    if path is None:
        context = _format_validation_context(
            command=command,
            output_path=expected_output_path,
            file_size=None,
            stdout_log_path=stdout_log_path,
            stderr_log_path=stderr_log_path,
        )
        raise RawConversionError(
            "raw_conversion_output_missing",
            f"Thermo RAW conversion did not produce a fresh mzML file. {context}",
        )
    try:
        stat = path.stat()
    except OSError as exc:
        raise RawConversionError("raw_conversion_output_missing", f"Converted mzML does not exist: {path}") from exc
    context = _format_validation_context(
        command=command,
        output_path=path,
        file_size=stat.st_size,
        stdout_log_path=stdout_log_path,
        stderr_log_path=stderr_log_path,
    )
    if stat.st_size <= 0:
        raise RawConversionError("raw_conversion_output_invalid", f"{invalid_subject} is empty: {path}. {context}")
    lower_name = path.name.lower()
    if lower_name.endswith((".mzml.gz", ".mzml.gzip")):
        raise RawConversionError(
            "raw_conversion_output_invalid",
            f"{invalid_subject} is gzip-compressed mzML, which P0 does not support: {path}. {context}",
        )
    if not lower_name.endswith(".mzml"):
        raise RawConversionError(
            "raw_conversion_output_invalid",
            f"{invalid_subject} is not an uncompressed mzML: {path}. {context}",
        )
    if not has_embedded_index_list_offset(path):
        raise RawConversionError(
            "raw_conversion_output_invalid",
            f"{invalid_subject} is missing embedded indexListOffset: {path}. {context}",
        )
    return path.resolve()


def validate_existing_mzml(path: Path) -> Path:
    try:
        return validate_converted_mzml(
            path,
            command=["skipped_existing_mzml"],
            invalid_subject="Existing same-stem mzML",
        )
    except RawConversionError as exc:
        if exc.code == "raw_conversion_output_invalid" and "missing embedded indexListOffset" in exc.message:
            raise RawConversionError(
                exc.code,
                f"existing mzML is not indexed: {exc.message}",
            ) from exc
        raise


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
    located_output_path: Path | None = None

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
        output_snapshot = _snapshot_output_mzml(request.raw_path, request.output_dir)
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
        located_output_path = _locate_changed_output_mzml(
            request.raw_path,
            request.output_dir,
            previous_snapshot=output_snapshot,
        )
        mzml_path = validate_converted_mzml(
            located_output_path,
            command=command,
            stdout_log_path=stdout_log_path,
            stderr_log_path=stderr_log_path,
            expected_output_path=request.output_dir / f"{request.raw_path.stem}.mzML",
        )
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
            mzml_path=located_output_path or locate_output_mzml(request.raw_path, request.output_dir),
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
