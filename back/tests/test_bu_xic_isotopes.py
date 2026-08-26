from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.bu.services import spectrum_facade, xic_service
from app.bu.services.precursor_isotopes import NEUTRON_MASS_DIFF_DA, build_precursor_isotope_targets
from app.services import spectrum_memory_wiring
from app.services.mzml_scan_index import (
    ScanIndexMissingError,
    ScanIndexStaleError,
    ScanMetadata,
)
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle


PRECURSOR_MZ = 477.3051452636719


def _match(*, charge: int | None = 2) -> dict[str, Any]:
    return {
        "match_id": 1,
        "run_id": 10,
        "sequence": "LLLPGELAK",
        "scan_number": -1,
        "precursor_mz": PRECURSOR_MZ,
        "precursor_charge": charge,
        "retention_time": 92.46,
        "extra_metadata": {"rt_start": 92.15, "rt_stop": 93.08},
        "run_metadata": {"raw_format": "mzml"},
    }


def _metadata(scan: int, rt: float) -> ScanMetadata:
    return ScanMetadata(
        scan_number=scan,
        native_id=f"scan={scan}",
        ms_level=1,
        retention_time=rt,
        tic=1000.0,
        bpc=500.0,
        precursor_mz=None,
        isolation_target_mz=None,
        isolation_lower_mz=None,
        isolation_upper_mz=None,
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


def test_precursor_isotope_targets_use_charge_spacing() -> None:
    targets = build_precursor_isotope_targets(PRECURSOR_MZ, 2)

    assert [target.label for target in targets] == ["M", "M+1", "M+2"]
    assert [target.isotope_index for target in targets] == [0, 1, 2]
    assert targets[0].target_mz == pytest.approx(PRECURSOR_MZ)
    assert targets[1].target_mz == pytest.approx(PRECURSOR_MZ + NEUTRON_MASS_DIFF_DA / 2)
    assert targets[2].target_mz == pytest.approx(PRECURSOR_MZ + 2 * NEUTRON_MASS_DIFF_DA / 2)


def test_xic_returns_m_m1_m2_traces_in_one_rt_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = build_precursor_isotope_targets(PRECURSOR_MZ, 2)
    m, m1, m2 = [target.target_mz for target in targets]
    spectra = {
        1: {
            "scan": 1,
            "ms_level": 1,
            "rt_seconds": 92.2 * 60.0,
            "mz": [m, m1, m2, 600.0],
            "intensity": [1000.0, 320.0, 90.0, 1.0],
        },
        2: {
            "scan": 2,
            "ms_level": 1,
            "rt_seconds": 92.8 * 60.0,
            "mz": [m, m1, m2, 600.0],
            "intensity": [800.0, 280.0, 70.0, 1.0],
        },
    }
    find_calls: list[tuple[Any, int, int, float, float]] = []
    read_calls: list[list[int]] = []

    def find_scans(
        session: Any,
        dataset_id: int,
        run_id: int,
        rt_start: float,
        rt_end: float,
    ) -> list[ScanMetadata]:
        find_calls.append((session, dataset_id, run_id, rt_start, rt_end))
        return [_metadata(1, 92.2), _metadata(2, 92.8)]

    def get_many(_session: Any, _dataset_id: int, _run_id: int, scans: list[int]):
        read_calls.append(scans)
        return {scan: spectra[scan] for scan in scans}, False

    monkeypatch.setattr(xic_service, "find_ms1_scans_in_rt_range", find_scans)
    monkeypatch.setattr(xic_service, "get_spectra_by_scans", get_many)
    _install_no_full_load_guards(monkeypatch)
    session = object()

    out = xic_service.get_match_xic(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
        ppm=10,
    )

    assert find_calls == [(session, 39, 10, 87.15, 98.08)]
    assert read_calls == [[1, 2]]
    assert out.precursor_charge == 2
    assert out.rt == [92.2, 92.8]
    assert [trace.label for trace in out.traces] == ["M", "M+1", "M+2"]
    assert [len(trace.intensity) for trace in out.traces] == [2, 2, 2]
    assert out.intensity == out.traces[0].intensity
    assert out.traces[0].intensity == [1000.0, 800.0]
    assert out.traces[1].intensity == [320.0, 280.0]
    assert out.traces[2].intensity == [90.0, 70.0]


def test_xic_invalid_charge_keeps_legacy_m_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    spectra = {
        1: {
            "scan": 1,
            "ms_level": 1,
            "rt_seconds": 92.2 * 60.0,
            "mz": [PRECURSOR_MZ],
            "intensity": [1000.0],
        }
    }
    monkeypatch.setattr(
        xic_service,
        "find_ms1_scans_in_rt_range",
        lambda *_args: [_metadata(1, 92.2)],
    )
    monkeypatch.setattr(
        xic_service,
        "get_spectra_by_scans",
        lambda *_args: ({1: spectra[1]}, False),
    )
    _install_no_full_load_guards(monkeypatch)

    out = xic_service.get_match_xic(None, {"dataset_id": 39}, _match(charge=None), ppm=10)  # type: ignore[arg-type]

    assert out.precursor_charge is None
    assert [trace.label for trace in out.traces] == ["M"]
    assert out.intensity == [1000.0]


def test_xic_uses_max_intensity_within_ppm_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    precursor_mz = 500.0
    match = {**_match(charge=None), "precursor_mz": precursor_mz}
    monkeypatch.setattr(
        xic_service,
        "find_ms1_scans_in_rt_range",
        lambda *_args: [_metadata(1, 92.2)],
    )
    monkeypatch.setattr(
        xic_service,
        "get_spectra_by_scans",
        lambda *_args: (
            {
                1: {
                    "scan": 1,
                    "ms_level": 1,
                    "rt_seconds": 92.2 * 60.0,
                    "mz": [499.99, 500.01, 501.0],
                    "intensity": [10.0, 20.0, 999.0],
                }
            },
            False,
        ),
    )
    _install_no_full_load_guards(monkeypatch)

    out = xic_service.get_match_xic(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        match,
        ppm=40.0,
    )

    assert out.intensity == [20.0]


def test_xic_empty_ms1_candidates_returns_empty_traces_without_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xic_service, "find_ms1_scans_in_rt_range", lambda *_args: [])
    monkeypatch.setattr(xic_service, "get_spectra_by_scans", _fail)
    _install_no_full_load_guards(monkeypatch)

    out = xic_service.get_match_xic(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
    )

    assert out.rt == []
    assert out.intensity == []
    assert [trace.label for trace in out.traces] == ["M", "M+1", "M+2"]
    assert all(trace.intensity == [] for trace in out.traces)


def test_xic_rejects_non_ms1_spectrum_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        xic_service,
        "find_ms1_scans_in_rt_range",
        lambda *_args: [_metadata(1, 92.2)],
    )
    monkeypatch.setattr(
        xic_service,
        "get_spectra_by_scans",
        lambda *_args: (
            {
                1: {
                    "scan": 1,
                    "ms_level": 2,
                    "rt_seconds": 92.2 * 60.0,
                    "mz": [],
                    "intensity": [],
                }
            },
            False,
        ),
    )
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        xic_service.get_match_xic(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "xic_ms1_scan_not_found"


@pytest.mark.parametrize(
    ("error", "error_name"),
    [
        (ScanIndexMissingError("scan_index_missing"), "scan_index_missing"),
        (ScanIndexStaleError("scan_index_stale"), "scan_index_stale"),
    ],
)
def test_xic_maps_scan_index_state_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    error_name: str,
) -> None:
    def raise_error(*_args: Any, **_kwargs: Any) -> list[ScanMetadata]:
        raise error

    monkeypatch.setattr(xic_service, "find_ms1_scans_in_rt_range", raise_error)
    monkeypatch.setattr(xic_service, "get_spectra_by_scans", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        xic_service.get_match_xic(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == error_name
    assert exc.value.detail["backfill_command"] == (
        "python scripts/backfill_mzml_scan_indexes.py --dataset-id 39 --run-id 10"
    )
