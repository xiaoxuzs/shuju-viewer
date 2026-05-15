"""Plain data contracts for LC-MS map construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class SpectrumFrame:
    """One spectrum frame in an LC-MS series."""

    scan: int
    rt_seconds: float
    ms_level: int
    mz: Sequence[Any]
    intensity: Sequence[Any]
    spec_id: int | None = None


@dataclass(frozen=True)
class LcmsMapRequest:
    """Provider-neutral request for a bounded LC-MS point cloud."""

    dataset_id: int
    run_id: int
    source: str
    slug: str
    source_root: str | None
    ms_level: int = 1
    center_scan: int | None = None
    center_spec_id: int | None = None
    center_rt_seconds: float | None = None
    precursor_mz: float | None = None
    rt_window_seconds: float = 240.0
    mz_window: float | None = 80.0
    frame_radius: int = 16
    rt_bins: int = 96
    mz_bins: int = 160
    max_points: int = 45_000


@dataclass(frozen=True)
class LcmsPointCloud:
    """Binned point cloud plus accounting metadata."""

    rt: list[float]
    mz: list[float]
    intensity: list[float]
    scan: list[int]
    ms_level: list[int]
    raw_point_count: int
    filtered_point_count: int
    binned_point_count: int
    returned_point_count: int
    rt_min: float
    rt_max: float
    mz_min: float
    mz_max: float
    intensity_min: float
    intensity_max: float
    mz_window_fallback: bool = False
