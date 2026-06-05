from __future__ import annotations

from typing import Any

import pytest

from app.bu.services import xic_service
from app.bu.services.precursor_isotopes import NEUTRON_MASS_DIFF_DA, build_precursor_isotope_targets


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
    monkeypatch.setattr(xic_service, "get_run_spectra", lambda *_args: spectra)

    out = xic_service.get_match_xic(None, {"dataset_id": 39}, _match(), ppm=10)  # type: ignore[arg-type]

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
    monkeypatch.setattr(xic_service, "get_run_spectra", lambda *_args: spectra)

    out = xic_service.get_match_xic(None, {"dataset_id": 39}, _match(charge=None), ppm=10)  # type: ignore[arg-type]

    assert out.precursor_charge is None
    assert [trace.label for trace in out.traces] == ["M"]
    assert out.intensity == [1000.0]
