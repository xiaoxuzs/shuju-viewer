"""Extract an mzML MS2 product ion chromatogram for a Bottom-Up match."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bu.services.scan_resolver import isolation_window_contains
from app.bu.services.spectrum_facade import ensure_mzml_match, get_run_spectra
from app.schemas import (
    BuProductXicBatchIn,
    BuProductXicBatchOut,
    BuProductXicBatchTraceOut,
    BuProductXicOut,
    BuProductXicPoint,
)


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


def _best_intensities(
    mz_values: list[Any],
    intensity_values: list[Any],
    targets: list[tuple[float, float]],
) -> list[float]:
    best = [0.0] * len(targets)
    for mz_raw, intensity_raw in zip(mz_values, intensity_values, strict=False):
        mz = _as_float(mz_raw)
        intensity = _as_float(intensity_raw)
        if mz is None or intensity is None:
            continue
        for index, (product_mz, tolerance) in enumerate(targets):
            if abs(mz - product_mz) <= tolerance:
                best[index] = max(best[index], intensity)
    return best


def _extract_product_xics(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    product_mzs: list[float],
    ppm: float,
    rt_window_override: tuple[float, float] | None = None,
) -> tuple[float, list[list[BuProductXicPoint]]]:
    ensure_mzml_match(match)
    precursor_mz = _as_float(match.get("precursor_mz"))
    if precursor_mz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product_xic_precursor_not_found")

    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
    spectra = get_run_spectra(session, dataset_id, run_id)
    rt_lo, rt_hi = rt_window_override or _rt_window(match)
    targets = [(product_mz, product_mz * ppm * 1e-6) for product_mz in product_mzs]
    points_by_target: list[list[BuProductXicPoint]] = [[] for _ in product_mzs]

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
        intensities = _best_intensities(
            spec.get("mz") or [],
            spec.get("intensity") or [],
            targets,
        )
        for index, intensity in enumerate(intensities):
            points_by_target[index].append(
                BuProductXicPoint(rt=rt_minutes, intensity=intensity, scan=int(spec_scan))
            )

    for points in points_by_target:
        points.sort(key=lambda point: (point.rt, point.scan))
    return precursor_mz, points_by_target


def get_match_product_xic(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    product_mz: float,
    ppm: float = 20.0,
) -> BuProductXicOut:
    precursor_mz, points_by_target = _extract_product_xics(
        session,
        dataset,
        match,
        product_mzs=[product_mz],
        ppm=ppm,
    )
    return BuProductXicOut(
        product_mz=product_mz,
        ppm=ppm,
        precursor_mz=precursor_mz,
        isolation_filter=True,
        points=points_by_target[0],
    )


def get_match_product_xics(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    request: BuProductXicBatchIn,
) -> BuProductXicBatchOut:
    rt_window_override = (
        (request.rt_window.start, request.rt_window.end)
        if request.rt_window is not None
        else None
    )
    _, points_by_target = _extract_product_xics(
        session,
        dataset,
        match,
        product_mzs=[ion.mz for ion in request.ions],
        ppm=request.tolerance_ppm,
        rt_window_override=rt_window_override,
    )
    traces = []
    for ion, points in zip(request.ions, points_by_target, strict=True):
        status_value = "ok" if any(point.intensity > 0 for point in points) else "no_signal"
        traces.append(
            BuProductXicBatchTraceOut(
                id=ion.id,
                ion=ion.ion,
                series=ion.series,
                position=ion.position,
                charge=ion.charge,
                mz=ion.mz,
                tolerance_ppm=request.tolerance_ppm,
                status=status_value,
                points=points,
            )
        )
    return BuProductXicBatchOut(traces=traces)
