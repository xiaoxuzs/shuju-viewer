"""Extract mzML MS1 XIC for a Bottom-Up match."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bu.services.precursor_isotopes import PrecursorIsotopeTarget, build_precursor_isotope_targets
from app.bu.services.spectrum_facade import ensure_mzml_match, get_run_spectra
from app.schemas import BuXicOut, BuXicTrace


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _rt_window(match: dict[str, Any]) -> tuple[float | None, float | None, float | None, float, float]:
    meta = _json_object(match.get("extra_metadata"))
    rt_apex = _as_float(match.get("retention_time")) or _as_float(meta.get("rt_apex"))
    rt_start = _as_float(meta.get("rt_start"))
    rt_stop = _as_float(meta.get("rt_stop"))
    if rt_start is None or rt_stop is None:
        if rt_apex is None:
            return rt_start, rt_stop, rt_apex, 0.0, 0.0
        rt_start = rt_apex
        rt_stop = rt_apex
    return rt_start, rt_stop, rt_apex, max(0.0, rt_start - 5.0), rt_stop + 5.0


def _best_intensities(
    mz_values: list[Any],
    intensity_values: list[Any],
    targets: list[PrecursorIsotopeTarget],
    ppm: float,
) -> dict[str, float]:
    best = {target.label: 0.0 for target in targets}
    windows = [(target.label, target.target_mz, target.target_mz * ppm * 1e-6) for target in targets]
    for mz_raw, intensity_raw in zip(mz_values, intensity_values, strict=False):
        mz = float(mz_raw)
        intensity = float(intensity_raw)
        for label, target_mz, mz_tol in windows:
            if abs(mz - target_mz) <= mz_tol:
                best[label] = max(best[label], intensity)
    return best


def get_match_xic(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    ppm: float = 10.0,
) -> BuXicOut:
    ensure_mzml_match(match)
    precursor_mz = _as_float(match.get("precursor_mz"))
    if precursor_mz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="xic_precursor_not_found")
    precursor_charge = _as_int(match.get("precursor_charge"))
    targets = build_precursor_isotope_targets(precursor_mz, precursor_charge)
    series = {target.label: [] for target in targets}

    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
    spectra = get_run_spectra(session, dataset_id, run_id)
    rt_start, rt_stop, rt_apex, rt_lo, rt_hi = _rt_window(match)
    rt: list[float] = []
    for spec in spectra.values():
        if int(spec.get("ms_level") or 1) != 1:
            continue
        spec_rt = (_as_float(spec.get("rt_seconds")) or 0.0) / 60.0
        if spec_rt < rt_lo or spec_rt > rt_hi:
            continue
        mz_values = spec.get("mz") or []
        intensity_values = spec.get("intensity") or []
        best = _best_intensities(mz_values, intensity_values, targets, ppm)
        rt.append(spec_rt)
        for target in targets:
            series[target.label].append(best[target.label])

    traces = [
        BuXicTrace(
            label=target.label,
            isotope_index=target.isotope_index,
            target_mz=target.target_mz,
            intensity=series[target.label],
        )
        for target in targets
    ]

    return BuXicOut(
        rt=rt,
        intensity=traces[0].intensity if traces else [],
        precursor_mz=precursor_mz,
        precursor_charge=precursor_charge,
        ppm=ppm,
        rt_apex=rt_apex,
        rt_start=rt_start,
        rt_stop=rt_stop,
        traces=traces,
    )


def xic_not_implemented() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")
