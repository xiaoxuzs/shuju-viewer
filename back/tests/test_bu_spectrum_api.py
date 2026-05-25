from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pyteomics import mass

from app.bu.services import chromatogram_service, mobility_service, spectrum_facade, xic_service
from app.schemas import BuChromatogramOut, BuMobilitySliceOut


def _match(*, raw_format: str = "mzml") -> dict[str, Any]:
    return {
        "match_id": 1,
        "run_id": 10,
        "sequence": "LLLPGELAK",
        "scan_number": -1,
        "precursor_mz": 477.3051452636719,
        "precursor_charge": 2,
        "retention_time": 92.46,
        "extra_metadata": {"rt_start": 92.15, "rt_stop": 93.08},
        "run_metadata": {"raw_format": raw_format},
    }


def _ms2_spec(scan: int = 67726) -> dict[str, Any]:
    sequence = "LLLPGELAK"
    mz = [
        float(mass.fast_mass(sequence[:pos], ion_type="b", charge=1))
        for pos in range(1, 7)
    ]
    mz += [
        float(mass.fast_mass(sequence[-pos:], ion_type="y", charge=1))
        for pos in range(1, 7)
    ]
    return {
        "scan": scan,
        "native_id": f"controllerType=0 controllerNumber=1 scan={scan}",
        "ms_level": 2,
        "rt_seconds": 92.4599 * 60.0,
        "mz": mz,
        "intensity": [1000.0 + i for i in range(len(mz))],
        "precursor": {
            "target_mz": 478.0,
            "lower_offset": 6.5,
            "upper_offset": 6.5,
            "selected_mz": 477.3051,
            "charge": 2,
        },
    }


def test_match_ms2_resolves_scan_and_matches_by_ions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", lambda *_args: {67726: _ms2_spec()})

    out = spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match(), ppm=20)  # type: ignore[arg-type]

    assert out.scan == 67726
    assert out.ms_level == 2
    assert len(out.matched_ions) >= 10


def test_bruker_match_ms2_is_unsupported() -> None:
    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_match_ms1_resolves_nearby_ms1_and_adds_precursor_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    spectra = {
        100: {
            "scan": 100,
            "native_id": "scan=100",
            "ms_level": 1,
            "rt_seconds": 92.30 * 60.0,
            "mz": [477.305, 600.0],
            "intensity": [100.0, 100.0],
        },
        101: {
            "scan": 101,
            "native_id": "scan=101",
            "ms_level": 1,
            "rt_seconds": 92.45 * 60.0,
            "mz": [477.305, 600.0],
            "intensity": [1000.0, 2000.0],
        },
    }
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", lambda *_args: spectra)

    out = spectrum_facade.get_match_ms1(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]

    assert out.scan == 101
    assert out.ms_level == 1
    assert out.markers[0].label == "precursor"
    assert out.markers[0].mz == pytest.approx(477.3051452636719)
    assert out.precursor and out.precursor.charge == 2


def test_bruker_match_ms1_is_unsupported() -> None:
    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms1(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_xic_uses_ms1_points_in_expanded_rt_window(monkeypatch: pytest.MonkeyPatch) -> None:
    spectra = {
        idx: {
            "scan": idx,
            "ms_level": 1,
            "rt_seconds": rt_min * 60.0,
            "mz": [477.304, 600.0],
            "intensity": [float(idx), 1.0],
        }
        for idx, rt_min in enumerate([87.2, 92.2, 92.8, 98.0], start=1)
    }
    monkeypatch.setattr(xic_service, "get_run_spectra", lambda *_args: spectra)

    out = xic_service.get_match_xic(None, {"dataset_id": 39}, _match(), ppm=10)  # type: ignore[arg-type]

    assert out.unit_rt == "min"
    assert out.rt_start == 92.15
    assert out.rt_stop == 93.08
    assert out.rt == [87.2, 92.2, 92.8, 98.0]
    assert out.intensity[1] > 0


def test_bruker_match_xic_is_unsupported() -> None:
    with pytest.raises(HTTPException) as exc:
        xic_service.get_match_xic(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_chromatogram_accepts_bruker_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chromatogram_service,
        "_run_row",
        lambda *_args: {"run_id": 11, "file_path": "sample.d", "run_metadata": {"raw_format": "bruker_d"}},
    )
    monkeypatch.setattr(
        chromatogram_service.tdf_chromatogram,
        "get_chromatogram",
        lambda **_kwargs: BuChromatogramOut(type="tic", rt=[1.0], intensity=[2.0], point_count_original=1),
    )

    out = chromatogram_service.get_chromatogram(None, {"dataset_id": 39}, 11, chrom_type="tic")  # type: ignore[arg-type]

    assert out.unit_rt == "min"
    assert out.rt == [1.0]


def test_mobility_slice_rejects_mzml_match() -> None:
    with pytest.raises(HTTPException) as exc:
        mobility_service.get_match_mobility_slice({"dataset_id": 39}, _match(raw_format="mzml"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_mobility_slice_accepts_bruker_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mobility_service.tdf_mobility_slice,
        "get_mobility_slice",
        lambda **_kwargs: BuMobilitySliceOut(mz=[500.0], one_over_k0=[1.1], intensity=[100.0], frame_id=7, rt_min=92.5),
    )

    out = mobility_service.get_match_mobility_slice(
        {"dataset_id": 39},
        {**_match(raw_format="bruker_d"), "file_path": "sample.d"},
    )

    assert out.frame_id == 7
    assert out.mz == [500.0]
