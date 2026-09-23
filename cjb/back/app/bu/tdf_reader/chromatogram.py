"""Bruker TDF TIC/BPC generation."""

from __future__ import annotations

from typing import Any, Literal

from app.bu.tdf_reader.root_resolver import resolve_run_tdf_root
from app.bu.tdf_reader.session_cache import get_session
from app.schemas import BuChromatogramOut

MAX_POINTS = 8000


def get_chromatogram(
    *,
    dataset_id: int,
    run: dict[str, Any],
    chrom_type: Literal["tic", "bpc"],
) -> BuChromatogramOut:
    dia = get_session(dataset_id=dataset_id, run_id=int(run["run_id"]), tdf_root=resolve_run_tdf_root(run))
    points: list[tuple[float, float]] = []
    for frame in dia.ms1:
        rt_min = float(frame.time) / 60.0
        if chrom_type == "tic":
            summary = getattr(frame, "summed_intensities", None)
            intensity = float(summary) if summary is not None else _centroid_sum(frame)
        else:
            summary = getattr(frame, "max_intensity", None)
            intensity = float(summary) if summary is not None else _centroid_max(frame)
        points.append((rt_min, intensity))

    points.sort(key=lambda item: item[0])
    rt = [p[0] for p in points]
    intensity = [p[1] for p in points]
    original = len(rt)
    rt, intensity, downsampled = _downsample(rt, intensity)
    return BuChromatogramOut(
        type=chrom_type,
        rt=rt,
        intensity=intensity,
        downsampled=downsampled,
        point_count_original=original,
    )


def _downsample(rt: list[float], intensity: list[float]) -> tuple[list[float], list[float], bool]:
    if len(rt) <= MAX_POINTS:
        return rt, intensity, False
    step = len(rt) / MAX_POINTS
    indexes = [min(int(i * step), len(rt) - 1) for i in range(MAX_POINTS)]
    return [rt[i] for i in indexes], [intensity[i] for i in indexes], True


def _centroid_sum(frame: Any) -> float:
    peaks = frame.centroid(min_peaks=2)
    return float(peaks[:, 1].sum()) if len(peaks) else 0.0


def _centroid_max(frame: Any) -> float:
    peaks = frame.centroid(min_peaks=2)
    return float(peaks[:, 1].max()) if len(peaks) else 0.0
