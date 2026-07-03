"""Locate local ThermoRawFileParser installations."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import BACKEND_ROOT
from app.raw_conversion.errors import RawConversionError

LOCAL_TOOL_FOLDER_VERSIONED = "ThermoRawFileParser1.4.5"
LOCAL_TOOL_FOLDER_GENERIC = "ThermoRawFileParser"
THERMO_RAW_FILE_PARSER_EXE = "ThermoRawFileParser.exe"


def _repo_root() -> Path:
    return BACKEND_ROOT.parent.resolve()


def get_default_thermo_raw_file_parser_candidates() -> tuple[Path, Path]:
    repo_root = _repo_root()
    return (
        repo_root / LOCAL_TOOL_FOLDER_VERSIONED / THERMO_RAW_FILE_PARSER_EXE,
        repo_root / LOCAL_TOOL_FOLDER_GENERIC / THERMO_RAW_FILE_PARSER_EXE,
    )


def _expand_configured_path(configured_path: str | os.PathLike[str]) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(os.fspath(configured_path)))
    return Path(expanded)


def _default_missing_message(candidates: tuple[Path, ...]) -> str:
    searched = "; ".join(str(path) for path in candidates)
    return (
        "ThermoRawFileParser executable was not found. "
        "THERMO_RAW_FILE_PARSER_EXE is not configured; searched default paths: "
        f"{searched}. expected local tool folder: {LOCAL_TOOL_FOLDER_VERSIONED}. "
        "Set THERMO_RAW_FILE_PARSER_EXE or place ThermoRawFileParser.exe under "
        f"<repo_root>/{LOCAL_TOOL_FOLDER_VERSIONED}/."
    )


def resolve_thermo_raw_file_parser_exe(configured_path: str | os.PathLike[str] | None) -> Path:
    if configured_path is not None and os.fspath(configured_path).strip():
        path = _expand_configured_path(configured_path)
        if path.is_file():
            return path.resolve()
        raise RawConversionError(
            "raw_converter_missing",
            f"ThermoRawFileParser configured path not found: {path}.",
        )

    candidates = get_default_thermo_raw_file_parser_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise RawConversionError("raw_converter_missing", _default_missing_message(candidates))
