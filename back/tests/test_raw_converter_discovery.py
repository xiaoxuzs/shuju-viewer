from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.raw_conversion import tool_discovery
from app.raw_conversion.errors import RawConversionError
from app.raw_conversion.service import convert_raw_files_for_import
from app.raw_conversion.tool_discovery import resolve_thermo_raw_file_parser_exe


def test_configured_thermo_raw_file_parser_path_has_priority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured tool" / "ThermoRawFileParser.exe"
    configured.parent.mkdir()
    configured.write_bytes(b"fake")
    local_default = tmp_path / "ThermoRawFileParser1.4.5" / "ThermoRawFileParser.exe"
    local_default.parent.mkdir()
    local_default.write_bytes(b"default")
    monkeypatch.setattr(
        tool_discovery,
        "get_default_thermo_raw_file_parser_candidates",
        lambda: (local_default,),
    )

    resolved = resolve_thermo_raw_file_parser_exe(str(configured))

    assert resolved == configured.resolve()


def test_configured_thermo_raw_file_parser_missing_reports_configured_path(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing" / "ThermoRawFileParser.exe"

    with pytest.raises(RawConversionError) as exc_info:
        resolve_thermo_raw_file_parser_exe(missing)

    assert exc_info.value.code == "raw_converter_missing"
    assert "configured path not found" in exc_info.value.message


def test_unconfigured_thermo_raw_file_parser_discovers_versioned_local_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    versioned = tmp_path / "repo" / "ThermoRawFileParser1.4.5" / "ThermoRawFileParser.exe"
    generic = tmp_path / "repo" / "ThermoRawFileParser" / "ThermoRawFileParser.exe"
    versioned.parent.mkdir(parents=True)
    generic.parent.mkdir(parents=True)
    versioned.write_bytes(b"versioned")
    generic.write_bytes(b"generic")
    monkeypatch.setattr(
        tool_discovery,
        "get_default_thermo_raw_file_parser_candidates",
        lambda: (versioned, generic),
    )

    resolved = resolve_thermo_raw_file_parser_exe(None)

    assert resolved == versioned.resolve()


def test_unconfigured_thermo_raw_file_parser_missing_lists_default_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    versioned = tmp_path / "repo" / "ThermoRawFileParser1.4.5" / "ThermoRawFileParser.exe"
    generic = tmp_path / "repo" / "ThermoRawFileParser" / "ThermoRawFileParser.exe"
    monkeypatch.setattr(
        tool_discovery,
        "get_default_thermo_raw_file_parser_candidates",
        lambda: (versioned, generic),
    )

    with pytest.raises(RawConversionError) as exc_info:
        resolve_thermo_raw_file_parser_exe(None)

    assert exc_info.value.code == "raw_converter_missing"
    assert "THERMO_RAW_FILE_PARSER_EXE is not configured" in exc_info.value.message
    assert "searched default paths" in exc_info.value.message
    assert "ThermoRawFileParser1.4.5" in exc_info.value.message


def test_raw_conversion_uses_discovered_local_tool_without_running_real_exe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dataset"
    source_root.mkdir()
    raw = source_root / "sample.raw"
    raw.write_bytes(b"raw")
    local_tool = tmp_path / "repo" / "ThermoRawFileParser1.4.5" / "ThermoRawFileParser.exe"
    local_tool.parent.mkdir(parents=True)
    local_tool.write_bytes(b"fake")
    monkeypatch.setattr(
        tool_discovery,
        "get_default_thermo_raw_file_parser_candidates",
        lambda: (local_tool, tmp_path / "missing" / "ThermoRawFileParser.exe"),
    )
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append({"command": command, **kwargs})
        output_dir = Path(command[4])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sample.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    batch = convert_raw_files_for_import(
        source_root=source_root,
        output_dir=source_root / ".viewer-derived" / "raw-converted-mzml",
        converter_exe=None,
        timeout_seconds=10,
    )

    assert batch.summary() == {"total_raw_files": 1, "converted": 1, "skipped": 0, "failed": 0}
    assert calls[0]["command"][0] == str(local_tool.resolve())
    assert calls[0]["shell"] is False
