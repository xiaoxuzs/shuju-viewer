"""High-level RAW conversion orchestration for import jobs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.raw_conversion.contracts import (
    RawConversionBatch,
    RawConversionRequest,
    RawConversionResult,
    RawFileCandidate,
)
from app.raw_conversion.discovery import discover_raw_file_candidates
from app.raw_conversion.errors import RawConversionError
from app.raw_conversion.thermo_raw_file_parser import (
    CONVERTER_NAME,
    run_thermo_raw_file_parser,
    validate_existing_mzml,
)
from app.raw_conversion.tool_discovery import resolve_thermo_raw_file_parser_exe

RawConversionProgress = Callable[[int, int, RawFileCandidate], None]


def _log_paths(logs_dir: Path, index: int, raw_path: Path) -> tuple[Path, Path]:
    prefix = f"{index:03d}-{raw_path.stem}"
    return logs_dir / f"{prefix}.stdout.log", logs_dir / f"{prefix}.stderr.log"


def _skipped_result(candidate: RawFileCandidate) -> RawConversionResult:
    mzml_path = (
        validate_existing_mzml(candidate.existing_mzml_path)
        if candidate.existing_mzml_path is not None
        else None
    )
    return RawConversionResult(
        raw_path=candidate.raw_path,
        mzml_path=mzml_path,
        status="skipped_existing_mzml",
        converter_name=CONVERTER_NAME,
        converter_version=None,
        command=[],
        started_at=None,
        finished_at=None,
        stdout_log_path=None,
        stderr_log_path=None,
        error_message=None,
    )


def convert_raw_files_for_import(
    *,
    source_root: Path,
    output_dir: Path,
    converter_exe: Path | None,
    timeout_seconds: int,
    force: bool = False,
    progress_callback: RawConversionProgress | None = None,
) -> RawConversionBatch:
    """Convert Thermo RAW files under *source_root* without touching the DB."""
    root = source_root.resolve()
    out_dir = output_dir.resolve()
    logs_dir = out_dir.parent / "raw-conversion-logs"
    candidates = discover_raw_file_candidates(source_root=root, output_dir=out_dir)
    results: list[RawConversionResult] = []
    raw_to_mzml: dict[str, Path] = {}
    resolved_converter_exe: Path | None = None

    for index, candidate in enumerate(candidates, start=1):
        if progress_callback is not None:
            progress_callback(index, len(candidates), candidate)

        if candidate.existing_mzml_path is not None and not force:
            try:
                result = _skipped_result(candidate)
            except RawConversionError as exc:
                result = RawConversionResult(
                    raw_path=candidate.raw_path,
                    mzml_path=candidate.existing_mzml_path,
                    status="failed",
                    converter_name=CONVERTER_NAME,
                    converter_version=None,
                    command=["skipped_existing_mzml"],
                    started_at=None,
                    finished_at=None,
                    stdout_log_path=None,
                    stderr_log_path=None,
                    error_message=exc.message,
                )
                results.append(result)
                raise RawConversionError(exc.code, exc.message, result=result) from exc
            results.append(result)
            if result.mzml_path is not None:
                raw_to_mzml[str(candidate.raw_path)] = result.mzml_path
            continue

        if resolved_converter_exe is None:
            resolved_converter_exe = resolve_thermo_raw_file_parser_exe(converter_exe)

        stdout_log, stderr_log = _log_paths(logs_dir, index, candidate.raw_path)
        request = RawConversionRequest(
            raw_path=candidate.raw_path,
            output_dir=candidate.expected_mzml_path.parent,
            converter_exe=resolved_converter_exe,
            timeout_seconds=timeout_seconds,
            force=force,
        )
        try:
            result = run_thermo_raw_file_parser(
                request,
                stdout_log_path=stdout_log,
                stderr_log_path=stderr_log,
            )
        except RawConversionError as exc:
            if exc.result is not None:
                results.append(exc.result)
            raise
        results.append(result)
        if result.mzml_path is not None:
            raw_to_mzml[str(candidate.raw_path)] = result.mzml_path

    return RawConversionBatch(results=tuple(results), raw_to_mzml=raw_to_mzml)
