from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.bu.tdf_reader import chromatogram, dia_windows, mobility_slice


@dataclass
class _Frame:
    frame_id: int
    time: float
    peaks: np.ndarray

    def centroid(self, min_peaks: int = 2) -> np.ndarray:
        return self.peaks


@dataclass
class _Window:
    isolation_mz: float
    isolation_width: float


class _Dia:
    def __init__(self) -> None:
        self.ms1 = [
            _Frame(1, 60.0, np.array([[500.0, 10.0, 1.10], [501.0, 20.0, 1.11]])),
            _Frame(2, 120.0, np.array([[600.0, 30.0, 1.20]])),
        ]
        self.windows = [_Window(500.004, 20.0), _Window(500.005, 20.0), _Window(700.0, 25.0)]


def test_tdf_chromatogram_uses_ms1_centroids(monkeypatch) -> None:
    monkeypatch.setattr(chromatogram, "resolve_run_tdf_root", lambda _run: "sample.d")
    monkeypatch.setattr(chromatogram, "get_session", lambda **_kwargs: _Dia())

    out = chromatogram.get_chromatogram(
        dataset_id=39,
        run={"run_id": 11, "file_path": "sample.d", "run_metadata": {"raw_format": "bruker_d"}},
        chrom_type="tic",
    )

    assert out.unit_rt == "min"
    assert out.rt == [1.0, 2.0]
    assert out.intensity == [30.0, 30.0]


def test_tdf_dia_windows_are_deduplicated(monkeypatch) -> None:
    monkeypatch.setattr(dia_windows, "resolve_run_tdf_root", lambda _run: "sample.d")
    monkeypatch.setattr(dia_windows, "get_session", lambda **_kwargs: _Dia())

    out = dia_windows.get_dia_windows(
        dataset_id=39,
        run={"run_id": 11, "file_path": "sample.d", "run_metadata": {"raw_format": "bruker_d"}},
    )

    assert out.window_count == 2
    assert [item.label for item in out.windows] == ["W1", "W2"]


def test_tdf_mobility_slice_uses_nearest_frame(monkeypatch) -> None:
    monkeypatch.setattr(mobility_slice, "resolve_run_tdf_root", lambda _run: "sample.d")
    monkeypatch.setattr(mobility_slice, "get_session", lambda **_kwargs: _Dia())

    out = mobility_slice.get_mobility_slice(
        dataset_id=39,
        run={"run_id": 11, "file_path": "sample.d", "run_metadata": {"raw_format": "bruker_d"}},
        rt_apex=1.98,
    )

    assert out.frame_id == 2
    assert out.mz == [600.0]
    assert out.one_over_k0 == [1.2]
