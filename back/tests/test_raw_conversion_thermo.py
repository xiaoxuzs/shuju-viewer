from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.raw_conversion.contracts import RawConversionRequest
from app.raw_conversion.errors import RawConversionError
from app.raw_conversion.thermo_raw_file_parser import (
    build_thermo_raw_file_parser_command,
    has_embedded_index_list_offset,
    locate_output_mzml,
    run_thermo_raw_file_parser,
    validate_converted_mzml,
)


def _command_value(command: list[str], prefix: str) -> str:
    for item in command:
        if item.startswith(prefix):
            return item[len(prefix) :]
    raise AssertionError(f"missing command argument: {prefix}")


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
        f"-i={raw}",
        f"-o={output_dir}",
        "-f=2",
        "-m=0",
    ]
    assert "-g" not in calls[0]["command"]
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
    assert "command:" in exc_info.value.message
    assert "output path:" in exc_info.value.message
    assert "file size:" in exc_info.value.message
    assert "searched marker: indexListOffset" in exc_info.value.message
    assert "stdout log:" in exc_info.value.message
    assert "stderr log:" in exc_info.value.message


def test_has_embedded_index_list_offset_detects_tail_marker(tmp_path: Path) -> None:
    path = tmp_path / "tail.mzML"
    path.write_bytes(b"<indexedmzML>" + (b"x" * 128) + b"<indexListOffset>99</indexListOffset></indexedmzML>")

    assert has_embedded_index_list_offset(path, tail_bytes=128)


def test_has_embedded_index_list_offset_falls_back_to_streaming_scan(tmp_path: Path) -> None:
    path = tmp_path / "large-window.mzML"
    path.write_bytes(b"<indexedmzML><indexListOffset>99</indexListOffset>" + (b"x" * 2048) + b"</indexedmzML>")

    assert has_embedded_index_list_offset(path, tail_bytes=16, chunk_bytes=32)


def test_validate_converted_mzml_rejects_gzip_output(tmp_path: Path) -> None:
    path = tmp_path / "sample.mzML.gz"
    path.write_bytes(b"gzip")

    with pytest.raises(RawConversionError) as exc_info:
        validate_converted_mzml(path)

    assert exc_info.value.code == "raw_conversion_output_invalid"
    assert "gzip-compressed mzML" in exc_info.value.message


def test_locate_output_mzml_ignores_stale_same_stem_file(tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")
    stale = tmp_path / "sample.mzML"
    stale.write_text("<mzML><indexListOffset>1</indexListOffset></mzML>", encoding="utf-8")
    modified_since_ns = stale.stat().st_mtime_ns + 1

    assert locate_output_mzml(raw, tmp_path, modified_since_ns=modified_since_ns) is None


def test_thermo_adapter_rejects_only_gzip_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")
    converter = tmp_path / "ThermoRawFileParser.exe"
    converter.write_bytes(b"fake")

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        output_dir = Path(_command_value(command, "-o="))
        (output_dir / "sample.mzML.gz").write_bytes(b"gzip")
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
    assert "gzip-compressed mzML" in exc_info.value.message
