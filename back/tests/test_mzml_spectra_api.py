from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from fastapi import HTTPException

from app.bu.services.chromatogram_summary import ChromatogramSummary
from app.api.v1 import mzml_spectra as mzml_spectra_api
from app.services.mzml_scan_index import MzmlScanIndex, ScanIndexMissingError
from app.services.mzml_scan_reader import (
    RunNotFoundError,
    SpectrumNotFoundError,
)
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle
from app.services import spectrum_memory_wiring


def _fail(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("whole-dataset mzML loading must not be called")


@pytest.mark.parametrize(
    ("ms_level", "precursor"),
    [
        (1, None),
        (
            2,
            {
                "parent_scan": 122,
                "target_mz": 500.2,
                "lower_offset": 1.0,
                "upper_offset": 1.0,
                "selected_mz": 500.2,
                "charge": 2,
            },
        ),
    ],
)
def test_mzml_spectrum_uses_indexed_reader_without_loading_dataset(
    monkeypatch: pytest.MonkeyPatch,
    ms_level: int,
    precursor: dict[str, Any] | None,
) -> None:
    expected = {
        "scan": 123,
        "native_id": "controllerType=0 controllerNumber=1 scan=123",
        "ms_level": ms_level,
        "rt_seconds": 12.5,
        "mz": [100.0, 200.0],
        "intensity": [10.0, 20.0],
        "precursor": precursor,
    }
    calls: list[tuple[Any, int, int, int]] = []

    def get_one(session: Any, dataset_id: int, run_id: int, scan_number: int):
        calls.append((session, dataset_id, run_id, scan_number))
        return expected, False

    monkeypatch.setattr(mzml_spectra_api, "get_spectrum_by_scan", get_one)
    monkeypatch.setattr(spectrum_memory_wiring, "ensure_mzml_dataset_resident", _fail)
    monkeypatch.setattr(DatasetMzmlBundle, "load", _fail)
    monkeypatch.setattr(
        "app.spectrum_memory.mzml_spectrum_extract.load_mzml_path_to_scan_map",
        _fail,
    )

    session = object()
    out = mzml_spectra_api.mzml_spectrum(39, 10, 123, session)  # type: ignore[arg-type]

    assert calls == [(session, 39, 10, 123)]
    assert out == {"dataset_id": 39, "run_id": 10, **expected}


def test_mzml_spectrum_returns_404_for_missing_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: Any, **_kwargs: Any):
        raise SpectrumNotFoundError("scan not found in mzML: 999")

    monkeypatch.setattr(mzml_spectra_api, "get_spectrum_by_scan", missing)

    with pytest.raises(HTTPException) as exc_info:
        mzml_spectra_api.mzml_spectrum(39, 10, 999, object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "scan not found in mzML: 999"


def test_mzml_spectrum_returns_404_when_run_is_not_in_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*_args: Any, **_kwargs: Any):
        raise RunNotFoundError("run not found")

    monkeypatch.setattr(mzml_spectra_api, "get_spectrum_by_scan", missing)

    with pytest.raises(HTTPException) as exc_info:
        mzml_spectra_api.mzml_spectrum(39, 999, 123, object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "run not found"


def test_generic_chromatogram_endpoint_does_not_require_bu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mzml_spectra_api,
        "_run_row",
        lambda *_args, **_kwargs: {
            "run_id": 10,
            "file_path": "run.mzML",
            "run_metadata": {"raw_format": "mzml", "mzml_file_path": "run.mzML"},
        },
    )
    monkeypatch.setattr(
        mzml_spectra_api.chromatogram_summary,
        "resolve_run_source_path",
        lambda _run: __import__("pathlib").Path("run.mzML"),
    )
    monkeypatch.setattr(
        mzml_spectra_api.chromatogram_summary,
        "load_summary",
        lambda **_kwargs: ChromatogramSummary(rt=[1.0, 2.0], tic=[10.0, 20.0], bpc=[5.0, 8.0], points_count=2),
    )

    out = mzml_spectra_api.mzml_run_chromatogram(39, 10, "bpc", object())  # type: ignore[arg-type]

    assert out.type == "bpc"
    assert out.rt == [1.0, 2.0]
    assert out.intensity == [5.0, 8.0]


def test_generic_scan_index_endpoint_returns_scan_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    index = MzmlScanIndex(
        scan_number=np.asarray([1, 2], dtype=np.int64),
        native_id=np.asarray(["scan=1", "scan=2"], dtype=np.str_),
        ms_level=np.asarray([1, 2], dtype=np.uint8),
        retention_time=np.asarray([0.5, 0.75], dtype=np.float64),
        tic=np.asarray([100.0, 200.0], dtype=np.float64),
        bpc=np.asarray([50.0, 80.0], dtype=np.float64),
        precursor_mz=np.asarray([np.nan, 500.2], dtype=np.float64),
        isolation_target_mz=np.asarray([np.nan, 500.0], dtype=np.float64),
        isolation_lower_mz=np.asarray([np.nan, 499.0], dtype=np.float64),
        isolation_upper_mz=np.asarray([np.nan, 501.0], dtype=np.float64),
    )
    monkeypatch.setattr(mzml_spectra_api, "load_scan_index", lambda *_args, **_kwargs: index)

    out = mzml_spectra_api.mzml_run_scan_index(39, 10, ms_level=2, session=object())  # type: ignore[arg-type]

    assert out["total"] == 1
    assert out["items"][0]["scan_number"] == 2
    assert out["items"][0]["precursor_mz"] == 500.2


def test_generic_scan_index_endpoint_reports_backfill_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: Any, **_kwargs: Any) -> None:
        raise ScanIndexMissingError("scan_index_missing")

    monkeypatch.setattr(mzml_spectra_api, "load_scan_index", missing)

    with pytest.raises(HTTPException) as exc_info:
        mzml_spectra_api.mzml_run_scan_index(39, 10, session=object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "scan_index_missing"
    assert "--dataset-id 39 --run-id 10" in exc_info.value.detail["backfill_command"]
