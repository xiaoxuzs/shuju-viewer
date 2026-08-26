from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.bu.services import product_xic_service, spectrum_facade
from app.schemas import BuProductXicBatchIn, BuProductXicBatchIonIn
from app.services import spectrum_memory_wiring
from app.services.mzml_scan_index import (
    ScanIndexMissingError,
    ScanIndexStaleError,
    ScanMetadata,
)
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle


def _match(*, raw_format: str = "mzml") -> dict[str, Any]:
    return {
        "match_id": 1,
        "run_id": 10,
        "precursor_mz": 500.0,
        "retention_time": 10.0,
        "extra_metadata": {"rt_start": 9.5, "rt_stop": 10.5},
        "run_metadata": {"raw_format": raw_format},
    }


def _metadata(scan: int, rt: float) -> ScanMetadata:
    return ScanMetadata(
        scan_number=scan,
        native_id=f"scan={scan}",
        ms_level=2,
        retention_time=rt,
        tic=1000.0,
        bpc=500.0,
        precursor_mz=500.0,
        isolation_target_mz=500.0,
        isolation_lower_mz=490.0,
        isolation_upper_mz=510.0,
    )


def _ion(identifier: str, mz: float) -> BuProductXicBatchIonIn:
    return BuProductXicBatchIonIn(
        id=identifier,
        ion=identifier,
        series="y",
        position=1,
        charge=1,
        mz=mz,
    )


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


def test_product_xic_batch_reads_each_candidate_once_and_extracts_all_ions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    find_calls: list[tuple[Any, int, int, float, float, float]] = []
    read_calls: list[list[int]] = []
    spectra = {
        1: {
            "scan": 1,
            "ms_level": 2,
            "rt_seconds": 9.8 * 60.0,
            "mz": [299.99, 300.01, 399.99, 400.01],
            "intensity": [10.0, 20.0, 30.0, 40.0],
        },
        2: {
            "scan": 2,
            "ms_level": 2,
            "rt_seconds": 10.2 * 60.0,
            "mz": [300.0, 400.0],
            "intensity": [50.0, 60.0],
        },
    }

    def find_scans(
        session: Any,
        dataset_id: int,
        run_id: int,
        rt_start: float,
        rt_end: float,
        precursor_mz: float,
    ) -> list[ScanMetadata]:
        find_calls.append((session, dataset_id, run_id, rt_start, rt_end, precursor_mz))
        return [_metadata(1, 9.8), _metadata(2, 10.2)]

    def get_many(_session: Any, _dataset_id: int, _run_id: int, scans: list[int]):
        read_calls.append(scans)
        return {scan: spectra[scan] for scan in scans}, False

    monkeypatch.setattr(product_xic_service, "find_product_xic_ms2_scans", find_scans)
    monkeypatch.setattr(product_xic_service, "get_spectra_by_scans", get_many)
    _install_no_full_load_guards(monkeypatch)
    request = BuProductXicBatchIn(
        tolerance_ppm=100.0,
        ions=[_ion("y1", 300.0), _ion("y2", 400.0)],
    )
    session = object()

    out = product_xic_service.get_match_product_xics(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
        request,
    )

    assert find_calls == [(session, 39, 10, 4.5, 15.5, 500.0)]
    assert read_calls == [[1, 2]]
    assert [point.intensity for point in out.traces[0].points] == [20.0, 50.0]
    assert [point.intensity for point in out.traces[1].points] == [40.0, 60.0]


def test_product_xic_empty_candidates_keeps_no_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_xic_service, "find_product_xic_ms2_scans", lambda *_args: [])
    monkeypatch.setattr(product_xic_service, "get_spectra_by_scans", _fail)
    _install_no_full_load_guards(monkeypatch)
    request = BuProductXicBatchIn(ions=[_ion("y1", 300.0)])

    out = product_xic_service.get_match_product_xics(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
        request,
    )

    assert out.traces[0].status == "no_signal"
    assert out.traces[0].points == []


def test_product_xic_rejects_non_ms2_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        product_xic_service,
        "find_product_xic_ms2_scans",
        lambda *_args: [_metadata(1, 10.0)],
    )
    monkeypatch.setattr(
        product_xic_service,
        "get_spectra_by_scans",
        lambda *_args: (
            {
                1: {
                    "scan": 1,
                    "ms_level": 1,
                    "rt_seconds": 10.0 * 60.0,
                    "mz": [],
                    "intensity": [],
                }
            },
            False,
        ),
    )
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        product_xic_service.get_match_product_xic(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
            product_mz=300.0,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "product_xic_ms2_scan_not_found"


@pytest.mark.parametrize(
    ("error", "error_name"),
    [
        (ScanIndexMissingError("scan_index_missing"), "scan_index_missing"),
        (ScanIndexStaleError("scan_index_stale"), "scan_index_stale"),
    ],
)
def test_product_xic_maps_scan_index_state_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    error_name: str,
) -> None:
    def raise_error(*_args: Any, **_kwargs: Any) -> list[ScanMetadata]:
        raise error

    monkeypatch.setattr(product_xic_service, "find_product_xic_ms2_scans", raise_error)
    monkeypatch.setattr(product_xic_service, "get_spectra_by_scans", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        product_xic_service.get_match_product_xic(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
            product_mz=300.0,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == error_name
    assert exc.value.detail["backfill_command"] == (
        "python scripts/backfill_mzml_scan_indexes.py --dataset-id 39 --run-id 10"
    )


def test_bruker_product_xic_does_not_use_mzml_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_xic_service, "find_product_xic_ms2_scans", _fail)
    monkeypatch.setattr(product_xic_service, "get_spectra_by_scans", _fail)

    with pytest.raises(HTTPException) as exc:
        product_xic_service.get_match_product_xic(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(raw_format="bruker_d"),
            product_mz=300.0,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"
