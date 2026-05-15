"""Spectrum-frame providers for LC-MS maps."""

from __future__ import annotations

from typing import Any

from app.lcms_map.contracts import LcmsMapRequest, SpectrumFrame
from app.services.spectrum_cache import SpectrumNotFoundError, get_ms1_spectrum, get_ms2_spectrum
from app.spectrum_memory import get_mzml_run_spectra


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

    loader = get_ms1_spectrum if request.ms_level == 1 else get_ms2_spectrum
    radius = max(0, int(request.frame_radius))
    start = max(0, int(center) - radius)
    stop = int(center) + radius
    frames: list[SpectrumFrame] = []

    for spec_id in range(start, stop + 1):
        try:
            raw = loader(request.slug, request.source_root, spec_id)
        except SpectrumNotFoundError:
            continue
        frame = _frame_from_topfd(raw, spec_id=spec_id, ms_level=request.ms_level)
        if frame is not None:
            frames.append(frame)

    frames.sort(key=lambda frame: (frame.rt_seconds, frame.scan, frame.spec_id or 0))
    return frames


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
