"""LC-MS map orchestration."""

from __future__ import annotations

import time
from typing import Any

from app.lcms_map.binning import build_point_cloud
from app.lcms_map.contracts import LcmsMapRequest, LcmsPointCloud
from app.lcms_map.providers import load_frames


def build_lcms_map(request: LcmsMapRequest) -> dict[str, Any]:
    """Build a frontend-ready 3D LC-MS point cloud."""
    started = time.perf_counter()
    frames = load_frames(request)

    mz_min: float | None = None
    mz_max: float | None = None
    if request.precursor_mz is not None and request.mz_window is not None and request.mz_window > 0:
        half = float(request.mz_window)
        mz_min = max(0.0, float(request.precursor_mz) - half)
        mz_max = float(request.precursor_mz) + half

    cloud = build_point_cloud(
        frames,
        rt_bins=request.rt_bins,
        mz_bins=request.mz_bins,
        max_points=request.max_points,
        mz_min=mz_min,
        mz_max=mz_max,
    )

    # Current 49 TopFD data can have a PrSM precursor window with sparse or no
    # signal in the local MS1 frames. Keep the panel useful by falling back to
    # the local full m/z range while reporting that fallback in metadata.
    if cloud.returned_point_count == 0 and mz_min is not None:
        cloud = build_point_cloud(
            frames,
            rt_bins=request.rt_bins,
            mz_bins=request.mz_bins,
            max_points=request.max_points,
            mz_min=None,
            mz_max=None,
            mz_window_fallback=True,
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return _to_response(request, cloud, frame_count=len(frames), generated_ms=elapsed_ms)


def _to_response(
    request: LcmsMapRequest,
    cloud: LcmsPointCloud,
    *,
    frame_count: int,
    generated_ms: float,
) -> dict[str, Any]:
    return {
        "source": request.source,
        "axes": {
            "x": {"key": "rt_seconds", "label": "RT", "min": cloud.rt_min, "max": cloud.rt_max},
            "y": {"key": "mz", "label": "m/z", "min": cloud.mz_min, "max": cloud.mz_max},
            "z": {
                "key": "intensity",
                "label": "Intensity",
                "min": cloud.intensity_min,
                "max": cloud.intensity_max,
                "scale": "log",
            },
        },
        "points": {
            "rt": cloud.rt,
            "mz": cloud.mz,
            "intensity": cloud.intensity,
            "scan": cloud.scan,
            "msLevel": cloud.ms_level,
        },
        "anchors": {
            "centerScan": request.center_scan,
            "centerSpecId": request.center_spec_id,
            "precursorMz": request.precursor_mz,
        },
        "meta": {
            "datasetId": request.dataset_id,
            "runId": request.run_id,
            "msLevel": request.ms_level,
            "frameCount": frame_count,
            "rawPointCount": cloud.raw_point_count,
            "filteredPointCount": cloud.filtered_point_count,
            "binnedPointCount": cloud.binned_point_count,
            "returnedPointCount": cloud.returned_point_count,
            "rtBins": request.rt_bins,
            "mzBins": request.mz_bins,
            "maxPoints": request.max_points,
            "mzWindowFallback": cloud.mz_window_fallback,
            "generatedMs": round(generated_ms, 3),
        },
    }
