"""RT/mz binning for LC-MS point clouds."""

from __future__ import annotations

import math
from typing import Iterable

from app.lcms_map.contracts import LcmsPointCloud, SpectrumFrame


def _to_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _iter_valid_peaks(
    frames: Iterable[SpectrumFrame],
    *,
    mz_min: float | None,
    mz_max: float | None,
):
    for frame in frames:
        mz_values = frame.mz
        intensity_values = frame.intensity
        n = min(len(mz_values), len(intensity_values))
        for i in range(n):
            mz = _to_float(mz_values[i])
            intensity = _to_float(intensity_values[i])
            if mz is None or intensity is None or intensity <= 0:
                yield frame, None, None, False
                continue
            if mz_min is not None and mz < mz_min:
                yield frame, mz, intensity, False
                continue
            if mz_max is not None and mz > mz_max:
                yield frame, mz, intensity, False
                continue
            yield frame, mz, intensity, True


def build_point_cloud(
    frames: list[SpectrumFrame],
    *,
    rt_bins: int,
    mz_bins: int,
    max_points: int,
    mz_min: float | None = None,
    mz_max: float | None = None,
    mz_window_fallback: bool = False,
) -> LcmsPointCloud:
    """Build a bounded point cloud by max-pooling intensity in RT/mz bins."""
    if not frames:
        return _empty_cloud(mz_window_fallback=mz_window_fallback)

    raw_count = 0
    filtered_count = 0
    rt_lo = math.inf
    rt_hi = -math.inf
    mz_lo = math.inf
    mz_hi = -math.inf

    for frame, mz, _intensity, keep in _iter_valid_peaks(frames, mz_min=mz_min, mz_max=mz_max):
        if mz is not None:
            raw_count += 1
        if not keep or mz is None:
            continue
        filtered_count += 1
        rt_lo = min(rt_lo, frame.rt_seconds)
        rt_hi = max(rt_hi, frame.rt_seconds)
        mz_lo = min(mz_lo, mz)
        mz_hi = max(mz_hi, mz)

    if filtered_count == 0:
        return _empty_cloud(raw_point_count=raw_count, mz_window_fallback=mz_window_fallback)

    rt_bins = max(2, int(rt_bins))
    mz_bins = max(2, int(mz_bins))
    max_points = max(1, int(max_points))
    rt_span = max(rt_hi - rt_lo, 1e-9)
    mz_span = max(mz_hi - mz_lo, 1e-9)

    # key -> (intensity, rt, mz, scan, ms_level)
    bins: dict[tuple[int, int], tuple[float, float, float, int, int]] = {}
    for frame, mz, intensity, keep in _iter_valid_peaks(frames, mz_min=mz_min, mz_max=mz_max):
        if not keep or mz is None or intensity is None:
            continue
        rt_i = min(rt_bins - 1, max(0, int(((frame.rt_seconds - rt_lo) / rt_span) * rt_bins)))
        mz_i = min(mz_bins - 1, max(0, int(((mz - mz_lo) / mz_span) * mz_bins)))
        key = (rt_i, mz_i)
        prev = bins.get(key)
        if prev is None or intensity > prev[0]:
            bins[key] = (intensity, frame.rt_seconds, mz, frame.scan, frame.ms_level)

    selected = list(bins.values())
    binned_count = len(selected)
    if len(selected) > max_points:
        selected = sorted(selected, key=lambda item: item[0], reverse=True)[:max_points]
    selected.sort(key=lambda item: (item[1], item[2]))

    intensities = [p[0] for p in selected]
    return LcmsPointCloud(
        rt=[p[1] for p in selected],
        mz=[p[2] for p in selected],
        intensity=intensities,
        scan=[p[3] for p in selected],
        ms_level=[p[4] for p in selected],
        raw_point_count=raw_count,
        filtered_point_count=filtered_count,
        binned_point_count=binned_count,
        returned_point_count=len(selected),
        rt_min=rt_lo,
        rt_max=rt_hi,
        mz_min=mz_lo,
        mz_max=mz_hi,
        intensity_min=min(intensities) if intensities else 0.0,
        intensity_max=max(intensities) if intensities else 0.0,
        mz_window_fallback=mz_window_fallback,
    )


def _empty_cloud(
    *,
    raw_point_count: int = 0,
    mz_window_fallback: bool = False,
) -> LcmsPointCloud:
    return LcmsPointCloud(
        rt=[],
        mz=[],
        intensity=[],
        scan=[],
        ms_level=[],
        raw_point_count=raw_point_count,
        filtered_point_count=0,
        binned_point_count=0,
        returned_point_count=0,
        rt_min=0.0,
        rt_max=0.0,
        mz_min=0.0,
        mz_max=0.0,
        intensity_min=0.0,
        intensity_max=0.0,
        mz_window_fallback=mz_window_fallback,
    )
