"""RT/mz binning for LC-MS point clouds."""

from __future__ import annotations

import math

from app.lcms_map.contracts import LcmsPointCloud, SpectrumFrame

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is a project dependency
    np = None  # type: ignore[assignment]


def _to_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


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
    if mz_min is not None and mz_max is not None and mz_max > mz_min:
        return _build_windowed_point_cloud_numpy(
            frames,
            rt_bins=rt_bins,
            mz_bins=mz_bins,
            max_points=max_points,
            mz_min=mz_min,
            mz_max=mz_max,
            mz_window_fallback=mz_window_fallback,
        )

    raw_count = 0
    rt_lo = math.inf
    rt_hi = -math.inf
    mz_lo = math.inf
    mz_hi = -math.inf
    filtered: list[tuple[float, float, float, int, int]] = []
    append_filtered = filtered.append

    for frame in frames:
        mz_values = frame.mz
        intensity_values = frame.intensity
        n = min(len(mz_values), len(intensity_values))
        raw_count += n
        rt = frame.rt_seconds
        scan = frame.scan
        ms_level = frame.ms_level
        for i in range(n):
            mz = _to_float(mz_values[i])
            if mz is None:
                continue
            if mz_min is not None and mz < mz_min:
                continue
            if mz_max is not None and mz > mz_max:
                break
            intensity = _to_float(intensity_values[i])
            if intensity is None or intensity <= 0:
                continue
            append_filtered((intensity, rt, mz, scan, ms_level))
            rt_lo = min(rt_lo, rt)
            rt_hi = max(rt_hi, rt)
            mz_lo = min(mz_lo, mz)
            mz_hi = max(mz_hi, mz)

    filtered_count = len(filtered)
    if filtered_count == 0:
        return _empty_cloud(raw_point_count=raw_count, mz_window_fallback=mz_window_fallback)

    rt_bins = max(2, int(rt_bins))
    mz_bins = max(2, int(mz_bins))
    max_points = max(1, int(max_points))
    rt_span = max(rt_hi - rt_lo, 1e-9)
    mz_span = max(mz_hi - mz_lo, 1e-9)

    # key -> (intensity, rt, mz, scan, ms_level)
    bins: dict[tuple[int, int], tuple[float, float, float, int, int]] = {}
    for intensity, rt, mz, scan, ms_level in filtered:
        rt_i = min(rt_bins - 1, max(0, int(((rt - rt_lo) / rt_span) * rt_bins)))
        mz_i = min(mz_bins - 1, max(0, int(((mz - mz_lo) / mz_span) * mz_bins)))
        key = (rt_i, mz_i)
        prev = bins.get(key)
        if prev is None or intensity > prev[0]:
            bins[key] = (intensity, rt, mz, scan, ms_level)

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


def _build_windowed_point_cloud(
    frames: list[SpectrumFrame],
    *,
    rt_bins: int,
    mz_bins: int,
    max_points: int,
    mz_min: float,
    mz_max: float,
    mz_window_fallback: bool,
) -> LcmsPointCloud:
    rt_bins = max(2, int(rt_bins))
    mz_bins = max(2, int(mz_bins))
    max_points = max(1, int(max_points))

    rt_lo = min(frame.rt_seconds for frame in frames)
    rt_hi = max(frame.rt_seconds for frame in frames)
    rt_span = max(rt_hi - rt_lo, 1e-9)
    mz_span = max(mz_max - mz_min, 1e-9)

    raw_count = 0
    filtered_count = 0
    bins: dict[tuple[int, int], tuple[float, float, float, int, int]] = {}

    for frame in frames:
        mz_values = frame.mz
        intensity_values = frame.intensity
        n = min(len(mz_values), len(intensity_values))
        raw_count += n
        rt = frame.rt_seconds
        rt_i = min(rt_bins - 1, max(0, int(((rt - rt_lo) / rt_span) * rt_bins)))
        scan = frame.scan
        ms_level = frame.ms_level
        for i in range(n):
            mz = _to_float(mz_values[i])
            if mz is None:
                continue
            if mz < mz_min:
                continue
            if mz > mz_max:
                break
            intensity = _to_float(intensity_values[i])
            if intensity is None or intensity <= 0:
                continue
            filtered_count += 1
            mz_i = min(mz_bins - 1, max(0, int(((mz - mz_min) / mz_span) * mz_bins)))
            key = (rt_i, mz_i)
            prev = bins.get(key)
            if prev is None or intensity > prev[0]:
                bins[key] = (intensity, rt, mz, scan, ms_level)

    if filtered_count == 0:
        return _empty_cloud(raw_point_count=raw_count, mz_window_fallback=mz_window_fallback)

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
        mz_min=mz_min,
        mz_max=mz_max,
        intensity_min=min(intensities) if intensities else 0.0,
        intensity_max=max(intensities) if intensities else 0.0,
        mz_window_fallback=mz_window_fallback,
    )


def _build_windowed_point_cloud_numpy(
    frames: list[SpectrumFrame],
    *,
    rt_bins: int,
    mz_bins: int,
    max_points: int,
    mz_min: float,
    mz_max: float,
    mz_window_fallback: bool,
) -> LcmsPointCloud:
    if np is None:
        return _build_windowed_point_cloud(
            frames,
            rt_bins=rt_bins,
            mz_bins=mz_bins,
            max_points=max_points,
            mz_min=mz_min,
            mz_max=mz_max,
            mz_window_fallback=mz_window_fallback,
        )

    rt_bins = max(2, int(rt_bins))
    mz_bins = max(2, int(mz_bins))
    max_points = max(1, int(max_points))
    total_bins = rt_bins * mz_bins

    rt_lo = min(frame.rt_seconds for frame in frames)
    rt_hi = max(frame.rt_seconds for frame in frames)
    rt_span = max(rt_hi - rt_lo, 1e-9)
    mz_span = max(mz_max - mz_min, 1e-9)

    max_intensity = np.full(total_bins, -np.inf, dtype=np.float64)
    rt_for_bin = np.zeros(total_bins, dtype=np.float64)
    mz_for_bin = np.zeros(total_bins, dtype=np.float64)
    scan_for_bin = np.zeros(total_bins, dtype=np.int64)
    ms_level_for_bin = np.zeros(total_bins, dtype=np.int64)

    raw_count = 0
    filtered_count = 0

    for frame in frames:
        mz_values = frame.mz
        intensity_values = frame.intensity
        n = min(len(mz_values), len(intensity_values))
        if n <= 0:
            continue
        raw_count += n
        try:
            mz_arr = np.asarray(mz_values[:n], dtype=np.float64)
            intensity_arr = np.asarray(intensity_values[:n], dtype=np.float64)
        except (TypeError, ValueError):
            return _build_windowed_point_cloud(
                frames,
                rt_bins=rt_bins,
                mz_bins=mz_bins,
                max_points=max_points,
                mz_min=mz_min,
                mz_max=mz_max,
                mz_window_fallback=mz_window_fallback,
            )

        mask = (
            np.isfinite(mz_arr)
            & np.isfinite(intensity_arr)
            & (intensity_arr > 0)
            & (mz_arr >= mz_min)
            & (mz_arr <= mz_max)
        )
        if not np.any(mask):
            continue

        mz_selected = mz_arr[mask]
        intensity_selected = intensity_arr[mask]
        filtered_count += int(intensity_selected.size)

        rt_i = min(rt_bins - 1, max(0, int(((frame.rt_seconds - rt_lo) / rt_span) * rt_bins)))
        mz_i = np.floor(((mz_selected - mz_min) / mz_span) * mz_bins).astype(np.int64, copy=False)
        mz_i = np.clip(mz_i, 0, mz_bins - 1)
        keys = rt_i * mz_bins + mz_i

        order = np.lexsort((-intensity_selected, keys))
        sorted_keys = keys[order]
        first_for_key = np.empty(sorted_keys.size, dtype=bool)
        first_for_key[0] = True
        first_for_key[1:] = sorted_keys[1:] != sorted_keys[:-1]
        winner_indices = order[first_for_key]
        winner_keys = keys[winner_indices]
        winner_intensity = intensity_selected[winner_indices]
        improved = winner_intensity > max_intensity[winner_keys]
        if not np.any(improved):
            continue

        improved_keys = winner_keys[improved]
        max_intensity[improved_keys] = winner_intensity[improved]
        rt_for_bin[improved_keys] = frame.rt_seconds
        mz_for_bin[improved_keys] = mz_selected[winner_indices[improved]]
        scan_for_bin[improved_keys] = frame.scan
        ms_level_for_bin[improved_keys] = frame.ms_level

    if filtered_count == 0:
        return _empty_cloud(raw_point_count=raw_count, mz_window_fallback=mz_window_fallback)

    selected_keys = np.flatnonzero(np.isfinite(max_intensity))
    binned_count = int(selected_keys.size)
    if selected_keys.size > max_points:
        strongest = np.argpartition(max_intensity[selected_keys], -max_points)[-max_points:]
        selected_keys = selected_keys[strongest]

    sort_order = np.lexsort((mz_for_bin[selected_keys], rt_for_bin[selected_keys]))
    selected_keys = selected_keys[sort_order]
    intensities = max_intensity[selected_keys]

    return LcmsPointCloud(
        rt=rt_for_bin[selected_keys].tolist(),
        mz=mz_for_bin[selected_keys].tolist(),
        intensity=intensities.tolist(),
        scan=scan_for_bin[selected_keys].astype(int).tolist(),
        ms_level=ms_level_for_bin[selected_keys].astype(int).tolist(),
        raw_point_count=raw_count,
        filtered_point_count=filtered_count,
        binned_point_count=binned_count,
        returned_point_count=int(selected_keys.size),
        rt_min=rt_lo,
        rt_max=rt_hi,
        mz_min=mz_min,
        mz_max=mz_max,
        intensity_min=float(np.min(intensities)) if intensities.size else 0.0,
        intensity_max=float(np.max(intensities)) if intensities.size else 0.0,
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
