from __future__ import annotations

from pathlib import Path

import pytest

from app.raw_conversion.discovery import collect_raw_files, discover_raw_file_candidates
from app.raw_conversion.service import convert_raw_files_for_import


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
