from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi import HTTPException

from app.bu.services import chromatogram_service, chromatogram_summary, spectrum_facade
from app.services import spectrum_memory_wiring
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle


def _fail(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("whole-dataset mzML loading must not be called")


def _run(source_path: Path, *, raw_format: str = "mzml") -> dict[str, Any]:
    return {
        "run_id": 10,
        "file_path": str(source_path),
        "run_metadata": {
            "raw_format": raw_format,
            "mzml_file_path": str(source_path),
        },
    }


def _install_no_full_load_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromatogram_service, "get_binary_chromatogram", lambda *_args: None)
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", _fail)
    monkeypatch.setattr(spectrum_memory_wiring, "ensure_mzml_dataset_resident", _fail)
    monkeypatch.setattr(DatasetMzmlBundle, "load", _fail)
    monkeypatch.setattr(
        "app.spectrum_memory.mzml_spectrum_extract.load_mzml_path_to_scan_map",
        _fail,
    )


def _write_valid_summary(tmp_path: Path) -> tuple[Path, chromatogram_summary.ChromatogramSummary]:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    summary = chromatogram_summary.ChromatogramSummary(
        rt=[1.0, 2.0],
        tic=[6.0, 6.0],
        bpc=[3.0, 5.0],
        points_count=2,
    )
    chromatogram_summary.write_summary(
        dataset_id=39,
        run_id=10,
        source_path=source_path,
        summary=summary,
        derived_root=tmp_path / "derived",
    )
    return source_path, summary


def test_calculate_summary_tic_bpc_values() -> None:
    summary = chromatogram_summary.calculate_summary_from_spectra(
        [
            {
                "ms_level": 1,
                "rt_seconds": 60.0,
                "intensity": np.array([1.0, 2.0, 3.0]),
            },
            {
                "ms_level": 2,
                "rt_seconds": 90.0,
                "intensity": np.array([100.0]),
            },
            {
                "ms_level": 1,
                "rt_seconds": 120.0,
                "intensity": np.array([5.0, 1.0]),
            },
        ]
    )

    assert summary.rt == [1.0, 2.0]
    assert summary.tic == [6.0, 6.0]
    assert summary.bpc == [3.0, 5.0]
    assert summary.points_count == 2


def test_generate_summary_streams_mzml_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    spectra = [
        {
            "ms level": 1,
            "scanList": {"scan": [{"scan start time": 1.0}]},
            "intensity array": np.array([1.0, 2.0]),
        }
    ]

    class FakeReader:
        def __enter__(self):
            return iter(spectra)

        def __exit__(self, *_args: Any) -> None:
            return None

    opened: list[str] = []

    def open_reader(path: str) -> FakeReader:
        opened.append(path)
        return FakeReader()

    monkeypatch.setattr(chromatogram_summary.mzml, "read", open_reader)

    summary = chromatogram_summary.generate_summary_from_mzml(source_path)

    assert opened == [str(source_path.resolve())]
    assert summary.tic == [3.0]
    assert summary.bpc == [2.0]


@pytest.mark.parametrize(
    ("chrom_type", "expected"),
    [("tic", [6.0, 6.0]), ("bpc", [3.0, 5.0])],
)
def test_mzml_chromatogram_reads_valid_summary_without_full_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chrom_type: str,
    expected: list[float],
) -> None:
    source_path, _summary = _write_valid_summary(tmp_path)
    monkeypatch.setattr(
        chromatogram_summary,
        "_derived_root",
        lambda _derived_root: (tmp_path / "derived").resolve(),
    )
    monkeypatch.setattr(chromatogram_service, "_run_row", lambda *_args: _run(source_path))
    _install_no_full_load_guards(monkeypatch)

    out = chromatogram_service.get_chromatogram(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        10,
        chrom_type=chrom_type,  # type: ignore[arg-type]
    )

    assert out.type == chrom_type
    assert out.unit_rt == "min"
    assert out.rt == [1.0, 2.0]
    assert out.intensity == expected
    assert out.downsampled is False
    assert out.point_count_original == 2


def test_raw_with_mzml_sidecar_chromatogram_reads_valid_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, _summary = _write_valid_summary(tmp_path)
    monkeypatch.setattr(
        chromatogram_summary,
        "_derived_root",
        lambda _derived_root: (tmp_path / "derived").resolve(),
    )
    monkeypatch.setattr(
        chromatogram_service,
        "_run_row",
        lambda *_args: _run(source_path, raw_format="thermo_raw"),
    )
    _install_no_full_load_guards(monkeypatch)

    out = chromatogram_service.get_chromatogram(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        10,
        chrom_type="tic",
    )

    assert out.rt == [1.0, 2.0]
    assert out.intensity == [6.0, 6.0]


def test_mzml_chromatogram_missing_summary_does_not_backfill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    monkeypatch.setattr(
        chromatogram_summary,
        "_derived_root",
        lambda _derived_root: (tmp_path / "derived").resolve(),
    )
    monkeypatch.setattr(chromatogram_service, "_run_row", lambda *_args: _run(source_path))
    monkeypatch.setattr(chromatogram_summary, "generate_summary_from_mzml", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        chromatogram_service.get_chromatogram(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            10,
            chrom_type="tic",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "chromatogram_summary_missing"


def test_mzml_chromatogram_stale_summary_does_not_backfill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, _summary = _write_valid_summary(tmp_path)
    source_path.write_bytes(b"updated-source")
    stat = source_path.stat()
    os.utime(source_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    monkeypatch.setattr(
        chromatogram_summary,
        "_derived_root",
        lambda _derived_root: (tmp_path / "derived").resolve(),
    )
    monkeypatch.setattr(chromatogram_service, "_run_row", lambda *_args: _run(source_path))
    monkeypatch.setattr(chromatogram_summary, "generate_summary_from_mzml", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        chromatogram_service.get_chromatogram(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            10,
            chrom_type="bpc",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "chromatogram_summary_stale"


def test_summary_requires_json_commit_marker(tmp_path: Path) -> None:
    source_path, _summary = _write_valid_summary(tmp_path)
    _npz_path, metadata_path = chromatogram_summary.summary_paths(
        39,
        10,
        derived_root=tmp_path / "derived",
    )
    metadata_path.unlink()

    with pytest.raises(
        chromatogram_summary.ChromatogramSummaryMissingError,
        match="chromatogram_summary_missing",
    ):
        chromatogram_summary.load_summary(
            dataset_id=39,
            run_id=10,
            source_path=source_path,
            derived_root=tmp_path / "derived",
        )


def test_summary_metadata_contains_source_fingerprint(tmp_path: Path) -> None:
    source_path, summary = _write_valid_summary(tmp_path)
    _npz_path, metadata_path = chromatogram_summary.summary_paths(
        39,
        10,
        derived_root=tmp_path / "derived",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_stat = source_path.stat()

    assert metadata["dataset_id"] == 39
    assert metadata["run_id"] == 10
    assert chromatogram_summary.normalize_source_path(Path(metadata["source_path"])) == (
        chromatogram_summary.normalize_source_path(source_path)
    )
    assert metadata["source_size"] == source_stat.st_size
    assert metadata["source_mtime_ns"] == source_stat.st_mtime_ns
    assert metadata["points_count"] == summary.points_count
    assert metadata["version"] == chromatogram_summary.SUMMARY_VERSION
    assert metadata["created_at"]


def test_mzml_chromatogram_preserves_downsampling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(chromatogram_service, "get_binary_chromatogram", lambda *_args: None)
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    point_count = chromatogram_service.MAX_POINTS + 10
    summary = chromatogram_summary.ChromatogramSummary(
        rt=[float(value) for value in range(point_count)],
        tic=[float(value) for value in range(point_count)],
        bpc=[float(value) for value in range(point_count)],
        points_count=point_count,
    )
    chromatogram_summary.write_summary(
        dataset_id=39,
        run_id=10,
        source_path=source_path,
        summary=summary,
        derived_root=tmp_path / "derived",
    )
    monkeypatch.setattr(
        chromatogram_summary,
        "_derived_root",
        lambda _derived_root: (tmp_path / "derived").resolve(),
    )
    monkeypatch.setattr(chromatogram_service, "_run_row", lambda *_args: _run(source_path))

    out = chromatogram_service.get_chromatogram(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        10,
        chrom_type="tic",
    )

    assert len(out.rt) == chromatogram_service.MAX_POINTS
    assert len(out.intensity) == chromatogram_service.MAX_POINTS
    assert out.downsampled is True
    assert out.point_count_original == point_count


def test_chromatogram_api_rejects_invalid_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        chromatogram_service.get_chromatogram(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            10,
            chrom_type="invalid",  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "invalid_chromatogram_type"
