from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.raw_conversion.contracts import RawConversionRequest
from app.raw_conversion.errors import RawConversionError
from app.raw_conversion.thermo_raw_file_parser import (
    build_thermo_raw_file_parser_command,
    run_thermo_raw_file_parser,
)


def test_missing_converter_reports_raw_converter_missing(tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")

    with pytest.raises(RawConversionError) as exc_info:
        build_thermo_raw_file_parser_command(
            RawConversionRequest(
                raw_path=raw,
                output_dir=tmp_path,
                converter_exe=None,
                timeout_seconds=1,
            )
        )

    assert exc_info.value.code == "raw_converter_missing"


def test_thermo_adapter_uses_list_command_and_supports_spaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "path with spaces"
    root.mkdir()
    raw = root / "sample one.raw"
    raw.write_bytes(b"raw")
    converter = root / "ThermoRawFileParser.exe"
    converter.write_bytes(b"fake")
    output_dir = root / "converted mzML"
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append({"command": command, **kwargs})
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sample one.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    result = run_thermo_raw_file_parser(
        RawConversionRequest(
            raw_path=raw,
            output_dir=output_dir,
            converter_exe=converter,
            timeout_seconds=10,
        ),
        stdout_log_path=root / "logs" / "stdout.log",
        stderr_log_path=root / "logs" / "stderr.log",
    )

    assert result.status == "converted"
    assert result.mzml_path == (output_dir / "sample one.mzML").resolve()
    assert calls[0]["command"] == [
        str(converter),
        "-i",
        str(raw),
        "-o",
        str(output_dir),
        "-f",
        "1",
    ]
    assert calls[0]["shell"] is False
    assert result.stdout_log_path is not None
    assert result.stdout_log_path.read_text(encoding="utf-8") == "ok"


def test_thermo_adapter_rejects_missing_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")
    converter = tmp_path / "ThermoRawFileParser.exe"
    converter.write_bytes(b"fake")

    def fake_run(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        (tmp_path / "sample.mzML").write_text("<mzML></mzML>", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    with pytest.raises(RawConversionError) as exc_info:
        run_thermo_raw_file_parser(
            RawConversionRequest(
                raw_path=raw,
                output_dir=tmp_path,
                converter_exe=converter,
                timeout_seconds=10,
            ),
            stdout_log_path=tmp_path / "stdout.log",
            stderr_log_path=tmp_path / "stderr.log",
        )

    assert exc_info.value.code == "raw_conversion_output_invalid"
