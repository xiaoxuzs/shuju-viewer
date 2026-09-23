"""Bruker TDF m/z by ion-mobility slice for a match RT."""

from __future__ import annotations

from typing import Any

from app.bu.tdf_reader.root_resolver import resolve_run_tdf_root
from app.bu.tdf_reader.session_cache import get_session
from app.schemas import BuMobilitySliceOut


def get_mobility_slice(
    *,
    dataset_id: int,
    run: dict[str, Any],
    rt_apex: float,
    rt_window: float = 0.1,
) -> BuMobilitySliceOut:
    dia = get_session(dataset_id=dataset_id, run_id=int(run["run_id"]), tdf_root=resolve_run_tdf_root(run))
    best_frame: Any | None = None
    best_delta: float | None = None
    for frame in dia.ms1:
        rt_min = float(frame.time) / 60.0
        delta = abs(rt_min - rt_apex)
        if delta > rt_window:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_frame = frame

    if best_frame is None:
        return BuMobilitySliceOut(mz=[], one_over_k0=[], intensity=[], frame_id=None, rt_min=None)

    peaks = best_frame.centroid(min_peaks=2)
    if len(peaks) == 0:
        return BuMobilitySliceOut(
            mz=[],
            one_over_k0=[],
            intensity=[],
            frame_id=int(best_frame.frame_id),
            rt_min=float(best_frame.time) / 60.0,
        )
    return BuMobilitySliceOut(
        mz=[float(value) for value in peaks[:, 0]],
        one_over_k0=[float(value) for value in peaks[:, 2]],
        intensity=[float(value) for value in peaks[:, 1]],
        frame_id=int(best_frame.frame_id),
        rt_min=float(best_frame.time) / 60.0,
    )
