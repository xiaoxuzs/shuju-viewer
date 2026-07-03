from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.raw_conversion.discovery import collect_raw_files, discover_raw_file_candidates
from app.raw_conversion.errors import RawConversionError
from app.raw_conversion.service import convert_raw_files_for_import


def _command_value(command: list[str], prefix: str) -> str:
    for item in command:
        if item.startswith(prefix):
            return item[len(prefix) :]
    raise AssertionError(f"missing command argument: {prefix}")


def test_collect_raw_files_is_case_insensitive_and_ignores_bruker_d(tmp_path: Path) -> None:
    raw_a = tmp_path / "sample.raw"
    raw_b = tmp_path / "nested" / "Other.RAW"
    raw_b.parent.mkdir()
    raw_a.write_bytes(b"raw")
    raw_b.write_bytes(b"raw")
    bruker = tmp_path / "bruker.raw.d"
    bruker.mkdir()
    (bruker / "analysis.tdf").write_bytes(b"sqlite")

    found = collect_raw_files(tmp_path)

    assert found == [raw_b.resolve(), raw_a.resolve()]


def test_discovery_maps_existing_same_stem_mzml(tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    mzml = tmp_path / "sample.mzML"
    raw.write_bytes(b"raw")
    mzml.write_text("<mzML><indexListOffset>1</indexListOffset></mzML>", encoding="utf-8")

    candidates = discover_raw_file_candidates(
        source_root=tmp_path,
        output_dir=tmp_path / ".viewer-derived" / "raw-converted-mzml",
    )

    assert len(candidates) == 1
    assert candidates[0].raw_path == raw.resolve()
    assert candidates[0].existing_mzml_path == mzml.resolve()


def test_service_skips_existing_mzml_without_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = tmp_path / "sample.raw"
    mzml = tmp_path / "sample.mzML"
    raw.write_bytes(b"raw")
    mzml.write_text("<mzML><indexListOffset>1</indexListOffset></mzML>", encoding="utf-8")

    def fail_resolver(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("converter discovery must not run when same-stem mzML is reused")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    batch = convert_raw_files_for_import(
        source_root=tmp_path,
        output_dir=tmp_path / ".viewer-derived" / "raw-converted-mzml",
        converter_exe=None,
        timeout_seconds=1,
    )

    assert batch.summary() == {"total_raw_files": 1, "converted": 0, "skipped": 1, "failed": 0}
    assert batch.results[0].status == "skipped_existing_mzml"
    assert batch.raw_to_mzml[str(raw.resolve())] == mzml.resolve()


def test_service_rejects_existing_mzml_without_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = tmp_path / "sample.raw"
    mzml = tmp_path / "sample.mzML"
    raw.write_bytes(b"raw")
    mzml.write_text("<mzML></mzML>", encoding="utf-8")

    def fail_resolver(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("converter discovery must not run when force=false and same-stem mzML exists")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    with pytest.raises(RawConversionError) as exc_info:
        convert_raw_files_for_import(
            source_root=tmp_path,
            output_dir=tmp_path / ".viewer-derived" / "raw-converted-mzml",
            converter_exe=None,
            timeout_seconds=1,
        )

    assert exc_info.value.code == "raw_conversion_output_invalid"
    assert "existing mzML is not indexed" in exc_info.value.message
    assert exc_info.value.result is not None
    assert exc_info.value.result.status == "failed"


def test_service_force_reconverts_existing_mzml_without_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = tmp_path / "sample.raw"
    mzml = tmp_path / "sample.mzML"
    converter = tmp_path / "ThermoRawFileParser.exe"
    raw.write_bytes(b"raw")
    mzml.write_text("<mzML></mzML>", encoding="utf-8")
    converter.write_bytes(b"fake")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        raw_path = Path(_command_value(command, "-i="))
        output_dir = Path(_command_value(command, "-o="))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{raw_path.stem}.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    batch = convert_raw_files_for_import(
        source_root=tmp_path,
        output_dir=tmp_path / ".viewer-derived" / "raw-converted-mzml",
        converter_exe=converter,
        timeout_seconds=1,
        force=True,
    )

    assert batch.summary() == {"total_raw_files": 1, "converted": 1, "skipped": 0, "failed": 0}
    assert calls


def test_service_no_raw_does_not_need_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.mzML").write_text("<mzML />", encoding="utf-8")

    def fail_resolver(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("converter discovery must not run without RAW files")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    batch = convert_raw_files_for_import(
        source_root=tmp_path,
        output_dir=tmp_path / ".viewer-derived" / "raw-converted-mzml",
        converter_exe=None,
        timeout_seconds=1,
    )

    assert batch.results == ()
    assert batch.raw_to_mzml == {}
