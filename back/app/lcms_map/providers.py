"""Spectrum-frame providers for LC-MS maps."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.lcms_map.contracts import LcmsMapRequest, SpectrumFrame
from app.services.spectrum_cache import (
    SpectrumNotFoundError,
    get_ms1_spectrum,
    get_ms2_spectrum,
    resolve_ms1_spectrum_path,
)
from app.spectrum_memory import get_mzml_run_spectra

_SCAN_RE = re.compile(rb'"scan"\s*:\s*(-?\d+)')
_RT_RE = re.compile(rb'"retention_time"\s*:\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')
_PEAK_RE = re.compile(rb'"mz"\s*:\s*"([^"]+)"\s*,\s*"intensity"\s*:\s*"([^"]+)"', re.DOTALL)


def load_frames(request: LcmsMapRequest) -> list[SpectrumFrame]:
    """Load normalized frames for the requested source."""
    if request.source == "mzml_memory":
        return _load_mzml_frames(request)
    if request.source == "topfd_js":
        return _load_topfd_frames(request)
    return []


def _load_topfd_frames(request: LcmsMapRequest) -> list[SpectrumFrame]:
    center = request.center_spec_id
    if center is None:
        return []

    radius = max(0, int(request.frame_radius))
    start = max(0, int(center) - radius)
    stop = int(center) + radius
    spec_ids = list(range(start, stop + 1))
    mz_min: float | None = None
    mz_max: float | None = None
    if request.ms_level == 1 and request.precursor_mz is not None and request.mz_window is not None:
        half = float(request.mz_window)
        mz_min = max(0.0, float(request.precursor_mz) - half)
        mz_max = float(request.precursor_mz) + half

    def load_one(spec_id: int) -> SpectrumFrame | None:
        if mz_min is not None and mz_max is not None:
            path = resolve_ms1_spectrum_path(request.slug, request.source_root, spec_id)
            return _frame_from_topfd_window(path, spec_id=spec_id, ms_level=request.ms_level, mz_min=mz_min, mz_max=mz_max)

        loader = get_ms1_spectrum if request.ms_level == 1 else get_ms2_spectrum
        try:
            raw = loader(request.slug, request.source_root, spec_id)
        except SpectrumNotFoundError:
            return None
        return _frame_from_topfd(raw, spec_id=spec_id, ms_level=request.ms_level)

    if len(spec_ids) <= 1:
        frames = [frame for frame in (load_one(spec_id) for spec_id in spec_ids) if frame is not None]
    else:
        workers = min(8, len(spec_ids))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            frames = [frame for frame in executor.map(load_one, spec_ids) if frame is not None]

    frames.sort(key=lambda frame: (frame.rt_seconds, frame.scan, frame.spec_id or 0))
    return frames


def _frame_from_topfd_window(
    path: Path,
    *,
    spec_id: int,
    ms_level: int,
    mz_min: float,
    mz_max: float,
) -> SpectrumFrame | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    scan_match = _SCAN_RE.search(data)
    rt_match = _RT_RE.search(data)
    scan = int(scan_match.group(1)) if scan_match else 0
    rt_seconds = float(rt_match.group(1)) if rt_match else 0.0
    mz: list[float] = []
    intensity: list[float] = []
    for match in _PEAK_RE.finditer(data):
        peak_mz = float(match.group(1))
        if peak_mz < mz_min:
            continue
        if peak_mz > mz_max:
            break
        peak_intensity = float(match.group(2))
        if peak_intensity <= 0:
            continue
        mz.append(peak_mz)
        intensity.append(peak_intensity)
    return SpectrumFrame(
        spec_id=spec_id,
        scan=scan,
        rt_seconds=rt_seconds,
        ms_level=ms_level,
        mz=mz,
        intensity=intensity,
    )


def _frame_from_topfd(raw: dict[str, Any], *, spec_id: int, ms_level: int) -> SpectrumFrame | None:
    peaks = raw.get("peaks")
    if not isinstance(peaks, list):
        return None
    mz: list[Any] = []
    intensity: list[Any] = []
    for peak in peaks:
        if not isinstance(peak, dict):
            continue
        mz.append(peak.get("mz"))
        intensity.append(peak.get("intensity"))
    return SpectrumFrame(
        spec_id=spec_id,
        scan=_int_or_zero(raw.get("scan")),
        rt_seconds=_float_or_zero(raw.get("retention_time")),
        ms_level=ms_level,
        mz=mz,
        intensity=intensity,
    )


def _load_mzml_frames(request: LcmsMapRequest) -> list[SpectrumFrame]:
    scan_map = get_mzml_run_spectra(request.dataset_id, request.run_id)
    if not scan_map:
        return []

    center_rt = request.center_rt_seconds
    if center_rt is None and request.center_scan is not None:
        center_spec = scan_map.get(request.center_scan)
        if center_spec is not None:
            center_rt = _float_or_none(center_spec.get("rt_seconds"))

    half_window = max(0.0, request.rt_window_seconds / 2.0)
    frames: list[SpectrumFrame] = []
    for scan, spec in scan_map.items():
        if _int_or_zero(spec.get("ms_level")) != request.ms_level:
            continue
        rt = _float_or_zero(spec.get("rt_seconds"))
        if center_rt is not None and abs(rt - center_rt) > half_window:
            continue
        mz = spec.get("mz")
        intensity = spec.get("intensity")
        if not isinstance(mz, list) or not isinstance(intensity, list):
            continue
        frames.append(
            SpectrumFrame(
                spec_id=None,
                scan=int(scan),
                rt_seconds=rt,
                ms_level=request.ms_level,
                mz=mz,
                intensity=intensity,
            )
        )

    frames.sort(key=lambda frame: (frame.rt_seconds, frame.scan))
    return frames


def _int_or_zero(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: object) -> float:
    out = _float_or_none(value)
    return out if out is not None else 0.0


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
