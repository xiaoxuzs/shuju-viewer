"""Extract an mzML MS2 product ion chromatogram for a Bottom-Up match."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bu.services.scan_resolver import isolation_window_contains
from app.bu.services.spectrum_facade import ensure_mzml_match, get_run_spectra
from app.schemas import BuProductXicOut, BuProductXicPoint


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rt_window(match: dict[str, Any]) -> tuple[float, float]:
    meta = _json_object(match.get("extra_metadata"))
    rt_start = _as_float(meta.get("rt_start"))
    rt_stop = _as_float(meta.get("rt_stop"))
    if rt_start is not None and rt_stop is not None:
        return max(0.0, min(rt_start, rt_stop) - 5.0), max(rt_start, rt_stop) + 5.0

    rt_apex = _as_float(match.get("retention_time")) or _as_float(meta.get("rt_apex"))
    if rt_apex is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product_xic_rt_not_found")
    return max(0.0, rt_apex - 5.0), rt_apex + 5.0


def _best_intensity(
    mz_values: list[Any],
    intensity_values: list[Any],
    product_mz: float,
    tolerance: float,
) -> float:
    best = 0.0
    for mz_raw, intensity_raw in zip(mz_values, intensity_values, strict=False):
        mz = _as_float(mz_raw)
        intensity = _as_float(intensity_raw)
        if mz is None or intensity is None:
            continue
        if abs(mz - product_mz) <= tolerance:
            best = max(best, intensity)
    return best


def get_match_product_xic(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    product_mz: float,
    ppm: float = 20.0,
) -> BuProductXicOut:
    ensure_mzml_match(match)
    precursor_mz = _as_float(match.get("precursor_mz"))
    if precursor_mz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product_xic_precursor_not_found")

    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
    spectra = get_run_spectra(session, dataset_id, run_id)
    rt_lo, rt_hi = _rt_window(match)
    tolerance = product_mz * ppm * 1e-6
    points: list[BuProductXicPoint] = []

    for spec_scan, spec in spectra.items():
        if int(spec.get("ms_level") or 1) != 2:
            continue
        rt_seconds = _as_float(spec.get("rt_seconds"))
        if rt_seconds is None:
            continue
        rt_minutes = rt_seconds / 60.0
        if rt_minutes < rt_lo or rt_minutes > rt_hi:
            continue
        if not isolation_window_contains(spec, precursor_mz):
            continue
        intensity = _best_intensity(
            spec.get("mz") or [],
            spec.get("intensity") or [],
            product_mz,
            tolerance,
        )
        points.append(BuProductXicPoint(rt=rt_minutes, intensity=intensity, scan=int(spec_scan)))

    points.sort(key=lambda point: (point.rt, point.scan))
    return BuProductXicOut(
        product_mz=product_mz,
        ppm=ppm,
        precursor_mz=precursor_mz,
        isolation_filter=True,
        points=points,
    )
