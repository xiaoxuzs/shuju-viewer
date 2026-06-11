from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.bu.services import spectrum_facade
from app.services import mzml_scan_index, spectrum_memory_wiring
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle


DATASET_ID = 40
RUN_ID = 39


def _fail(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("whole-dataset mzML loading must not be called")


def _install_no_full_load_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", _fail)
    monkeypatch.setattr(spectrum_memory_wiring, "ensure_mzml_dataset_resident", _fail)
    monkeypatch.setattr(DatasetMzmlBundle, "load", _fail)
    monkeypatch.setattr(
        "app.spectrum_memory.mzml_spectrum_extract.load_mzml_path_to_scan_map",
        _fail,
    )


def _spectrum(
    scan_number: int,
    *,
    ms_level: int,
    rt_minutes: float,
    intensity: list[float],
    selected_mz: float | None = None,
    target_mz: float | None = None,
    lower_offset: float | None = None,
    upper_offset: float | None = None,
) -> dict[str, Any]:
    spectrum: dict[str, Any] = {
        "id": f"controllerType=0 controllerNumber=1 scan={scan_number}",
        "ms level": ms_level,
        "scanList": {"scan": [{"scan start time": rt_minutes * 60.0}]},
        "intensity array": np.asarray(intensity, dtype=np.float64),
    }
    if ms_level == 2:
        spectrum["precursorList"] = {
            "precursor": [
                {
                    "isolationWindow": {
                        "isolation window target m/z": target_mz,
                        "isolation window lower offset": lower_offset,
                        "isolation window upper offset": upper_offset,
                    },
                    "selectedIonList": {
                        "selectedIon": [{"selected ion m/z": selected_mz}]
                    },
                }
            ]
        }
    return spectrum


def _example_index() -> mzml_scan_index.MzmlScanIndex:
    return mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(1, ms_level=1, rt_minutes=1.0, intensity=[1.0, 2.0, 3.0]),
            _spectrum(
                2,
                ms_level=2,
                rt_minutes=1.5,
                intensity=[5.0, 1.0],
                selected_mz=501.0,
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=15.0,
            ),
        ]
    )


def _write_example_index(tmp_path: Path) -> tuple[Path, Path]:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=_example_index(),
        derived_root=tmp_path / "derived",
    )
    return source_path, tmp_path / "derived"


def _use_source_path(
    monkeypatch: pytest.MonkeyPatch,
    source_path: Path,
) -> None:
    monkeypatch.setattr(
        mzml_scan_index,
        "_resolve_source_path",
        lambda _session, _dataset_id, _run_id: source_path,
    )


def test_build_scan_index_extracts_metadata_without_peak_arrays() -> None:
    index = _example_index()

    assert index.scan_number.tolist() == [1, 2]
    assert index.native_id.tolist() == [
        "controllerType=0 controllerNumber=1 scan=1",
        "controllerType=0 controllerNumber=1 scan=2",
    ]
    assert index.ms_level.tolist() == [1, 2]
    assert index.retention_time.tolist() == [1.0, 1.5]
    assert index.tic.tolist() == [6.0, 6.0]
    assert index.bpc.tolist() == [3.0, 5.0]
    assert np.isnan(index.precursor_mz[0])
    assert index.precursor_mz[1] == 501.0
    assert index.isolation_target_mz[1] == 500.0
    assert index.isolation_lower_mz[1] == 490.0
    assert index.isolation_upper_mz[1] == 515.0
    assert "mz" not in mzml_scan_index.INDEX_FIELDS
    assert "intensity" not in mzml_scan_index.INDEX_FIELDS


def test_generate_scan_index_streams_reader_without_tolist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")

    class NoToListArray:
        def __array__(self, dtype: Any = None) -> np.ndarray:
            return np.asarray([1.0, 2.0], dtype=dtype)

        def tolist(self) -> None:
            raise AssertionError("scan index generation must not call tolist")

    spectrum = _spectrum(1, ms_level=1, rt_minutes=1.0, intensity=[])
    spectrum["intensity array"] = NoToListArray()

    class FakeReader:
        def __enter__(self) -> "FakeReader":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def __iter__(self):
            yield spectrum

    monkeypatch.setattr(mzml_scan_index.mzml, "read", lambda _path: FakeReader())

    index = mzml_scan_index.generate_scan_index_from_mzml(source_path)

    assert index.scan_count == 1
    assert index.tic.tolist() == [3.0]


def test_write_scan_index_persists_metadata_and_json_commit_marker(tmp_path: Path) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    npz_path, metadata_path = mzml_scan_index.scan_index_paths(
        DATASET_ID,
        RUN_ID,
        derived_root=derived_root,
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_stat = source_path.stat()

    assert npz_path.is_file()
    assert metadata_path.is_file()
    assert metadata["version"] == mzml_scan_index.INDEX_VERSION
    assert metadata["dataset_id"] == DATASET_ID
    assert metadata["run_id"] == RUN_ID
    assert mzml_scan_index.normalize_source_path(Path(metadata["source_path"])) == (
        mzml_scan_index.normalize_source_path(source_path)
    )
    assert metadata["source_size"] == source_stat.st_size
    assert metadata["source_mtime_ns"] == source_stat.st_mtime_ns
    assert metadata["scan_count"] == 2
    assert metadata["ms1_count"] == 1
    assert metadata["ms2_count"] == 1
    assert metadata["retention_time_unit"] == "min"
    assert metadata["fields"] == list(mzml_scan_index.INDEX_FIELDS)
    with np.load(npz_path, allow_pickle=False) as arrays:
        assert set(arrays.files) == set(mzml_scan_index.INDEX_FIELDS)
        assert "m/z array" not in arrays.files
        assert "intensity array" not in arrays.files


def test_scan_index_requires_json_commit_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    _npz_path, metadata_path = mzml_scan_index.scan_index_paths(
        DATASET_ID,
        RUN_ID,
        derived_root=derived_root,
    )
    metadata_path.unlink()
    _use_source_path(monkeypatch, source_path)

    with pytest.raises(mzml_scan_index.ScanIndexMissingError, match="scan_index_missing"):
        mzml_scan_index.load_scan_index(
            None,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
            derived_root=derived_root,
        )


def test_missing_scan_index_does_not_rebuild_or_load_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    _use_source_path(monkeypatch, source_path)
    monkeypatch.setattr(mzml_scan_index, "generate_scan_index_from_mzml", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(mzml_scan_index.ScanIndexMissingError, match="scan_index_missing"):
        mzml_scan_index.load_scan_index(
            None,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
            derived_root=tmp_path / "derived",
        )


def test_stale_scan_index_does_not_rebuild_or_load_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    source_path.write_bytes(b"updated-source")
    stat = source_path.stat()
    os.utime(source_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    _use_source_path(monkeypatch, source_path)
    monkeypatch.setattr(mzml_scan_index, "generate_scan_index_from_mzml", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(mzml_scan_index.ScanIndexStaleError, match="scan_index_stale"):
        mzml_scan_index.load_scan_index(
            None,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
            derived_root=derived_root,
        )


def test_native_id_parse_failure_reports_native_id() -> None:
    native_id = "sample=alpha spectrum=123"

    with pytest.raises(mzml_scan_index.ScanIndexUnsupportedError, match=native_id):
        mzml_scan_index.build_scan_index_from_spectra(
            [{"id": native_id, "ms level": 1, "intensity array": np.array([])}]
        )


def test_duplicate_scan_number_is_rejected() -> None:
    with pytest.raises(
        mzml_scan_index.ScanIndexUnsupportedError,
        match="multiple native IDs map to scan number 1",
    ):
        mzml_scan_index.build_scan_index_from_spectra(
            [
                _spectrum(1, ms_level=1, rt_minutes=1.0, intensity=[]),
                {
                    **_spectrum(1, ms_level=1, rt_minutes=2.0, intensity=[]),
                    "id": "scan=1",
                },
            ]
        )


def test_generate_scan_index_rejects_gzip(tmp_path: Path) -> None:
    source_path = tmp_path / "run.mzML.gz"
    source_path.write_bytes(b"gzip")

    with pytest.raises(mzml_scan_index.ScanIndexUnsupportedError, match="gzip-compressed"):
        mzml_scan_index.generate_scan_index_from_mzml(source_path)


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> "_Result":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._row


class _Session:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        return _Result(self._row)


def test_resolve_source_path_rejects_non_mzml_run() -> None:
    session = _Session({"run_metadata": {"raw_format": "tdf"}})

    with pytest.raises(mzml_scan_index.ScanIndexUnsupportedError, match="run is not mzML"):
        mzml_scan_index._resolve_source_path(  # noqa: SLF001
            session,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
        )


def test_find_scan_by_number_uses_only_derived_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    _use_source_path(monkeypatch, source_path)
    _install_no_full_load_guards(monkeypatch)

    result = mzml_scan_index.find_scan_by_number(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        2,
        derived_root=derived_root,
    )

    assert result.scan_number == 2
    assert result.ms_level == 2
    assert result.precursor_mz == 501.0


def test_find_scan_by_number_reports_missing_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    _use_source_path(monkeypatch, source_path)

    with pytest.raises(mzml_scan_index.ScanMetadataNotFoundError, match="scan_not_found: 999"):
        mzml_scan_index.find_scan_by_number(
            None,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
            999,
            derived_root=derived_root,
        )


def test_find_nearest_ms1_scan_orders_by_tic_distance_then_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(30, ms_level=1, rt_minutes=10.10, intensity=[20.0]),
            _spectrum(20, ms_level=1, rt_minutes=9.95, intensity=[20.0]),
            _spectrum(10, ms_level=1, rt_minutes=10.05, intensity=[20.0]),
            _spectrum(5, ms_level=1, rt_minutes=10.00, intensity=[19.0]),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    result = mzml_scan_index.find_nearest_ms1_scan(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        10.0,
        derived_root=derived_root,
    )

    assert result.scan_number == 10


def test_find_ms1_scans_in_rt_range_is_closed_and_sorted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(3, ms_level=1, rt_minutes=2.0, intensity=[1.0]),
            _spectrum(2, ms_level=1, rt_minutes=1.0, intensity=[1.0]),
            _spectrum(1, ms_level=1, rt_minutes=1.0, intensity=[1.0]),
            _spectrum(4, ms_level=2, rt_minutes=1.5, intensity=[1.0]),
            _spectrum(5, ms_level=1, rt_minutes=3.0, intensity=[1.0]),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_ms1_scans_in_rt_range(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        1.0,
        2.0,
        derived_root=derived_root,
    )

    assert [result.scan_number for result in results] == [1, 2, 3]
    assert all(result.ms_level == 1 for result in results)


def test_find_ms1_scans_in_rt_range_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_ms1_scans_in_rt_range(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        10.0,
        11.0,
        derived_root=derived_root,
    )

    assert results == []


def test_find_ms2_scans_in_rt_range_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(1, ms_level=2, rt_minutes=1.0, intensity=[1.0]),
            _spectrum(2, ms_level=2, rt_minutes=2.0, intensity=[1.0]),
            _spectrum(3, ms_level=2, rt_minutes=3.0, intensity=[1.0]),
            _spectrum(4, ms_level=1, rt_minutes=2.0, intensity=[1.0]),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_ms2_scans_in_rt_range(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        1.0,
        2.0,
        derived_root=derived_root,
    )

    assert [result.scan_number for result in results] == [1, 2]


def test_find_ms2_scans_by_rt_and_isolation_uses_absolute_bounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(
                1,
                ms_level=2,
                rt_minutes=1.0,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(
                2,
                ms_level=2,
                rt_minutes=1.5,
                intensity=[1.0],
                target_mz=700.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_ms2_scans_by_rt_and_isolation(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        1.0,
        2.0,
        precursor_mz=489.5,
        tolerance=0.5,
        derived_root=derived_root,
    )

    assert [result.scan_number for result in results] == [1]


def test_find_product_xic_ms2_scans_filters_rt_isolation_and_selected_mz(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(
                3,
                ms_level=2,
                rt_minutes=2.0,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(
                1,
                ms_level=2,
                rt_minutes=1.0,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(
                2,
                ms_level=2,
                rt_minutes=1.5,
                intensity=[1.0],
                selected_mz=501.5,
            ),
            _spectrum(
                4,
                ms_level=2,
                rt_minutes=1.5,
                intensity=[1.0],
                target_mz=700.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(5, ms_level=1, rt_minutes=1.5, intensity=[1.0]),
            _spectrum(
                6,
                ms_level=2,
                rt_minutes=3.0,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_product_xic_ms2_scans(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        1.0,
        2.0,
        500.0,
        derived_root=derived_root,
    )

    assert [result.scan_number for result in results] == [1, 2, 3]
    assert all(result.ms_level == 2 for result in results)


def test_find_product_xic_ms2_scans_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path, derived_root = _write_example_index(tmp_path)
    _use_source_path(monkeypatch, source_path)

    results = mzml_scan_index.find_product_xic_ms2_scans(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        10.0,
        11.0,
        500.0,
        derived_root=derived_root,
    )

    assert results == []


def test_find_nearest_ms2_scan_orders_by_rt_distance_then_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(
                30,
                ms_level=2,
                rt_minutes=10.10,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(
                20,
                ms_level=2,
                rt_minutes=9.95,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
            _spectrum(
                10,
                ms_level=2,
                rt_minutes=10.05,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            ),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    result = mzml_scan_index.find_nearest_ms2_scan(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        10.0,
        500.0,
        max_delta_minutes=0.5,
        derived_root=derived_root,
    )

    assert result.scan_number == 10


def test_find_nearest_ms2_scan_supports_selected_mz_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(
                1,
                ms_level=2,
                rt_minutes=1.0,
                intensity=[1.0],
                selected_mz=501.5,
            ),
            _spectrum(
                2,
                ms_level=2,
                rt_minutes=1.1,
                intensity=[1.0],
                selected_mz=600.0,
            ),
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    result = mzml_scan_index.find_nearest_ms2_scan(
        None,  # type: ignore[arg-type]
        DATASET_ID,
        RUN_ID,
        1.0,
        500.0,
        max_delta_minutes=0.5,
        derived_root=derived_root,
    )

    assert result.scan_number == 1


def test_find_nearest_ms2_scan_applies_optional_rt_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.mzML"
    source_path.write_bytes(b"source")
    index = mzml_scan_index.build_scan_index_from_spectra(
        [
            _spectrum(
                1,
                ms_level=2,
                rt_minutes=2.0,
                intensity=[1.0],
                target_mz=500.0,
                lower_offset=10.0,
                upper_offset=10.0,
            )
        ]
    )
    derived_root = tmp_path / "derived"
    mzml_scan_index.write_scan_index(
        dataset_id=DATASET_ID,
        run_id=RUN_ID,
        source_path=source_path,
        index=index,
        derived_root=derived_root,
    )
    _use_source_path(monkeypatch, source_path)

    with pytest.raises(mzml_scan_index.ScanMetadataNotFoundError):
        mzml_scan_index.find_nearest_ms2_scan(
            None,  # type: ignore[arg-type]
            DATASET_ID,
            RUN_ID,
            1.0,
            500.0,
            max_delta_minutes=0.5,
            derived_root=derived_root,
        )
