from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1 import mzml_spectra as mzml_spectra_api
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
