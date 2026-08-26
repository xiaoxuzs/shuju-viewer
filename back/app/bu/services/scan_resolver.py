"""Resolve a peptide match to an mzML MS2 scan."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


DIA_ISOLATION_WINDOW_MZ_TOLERANCE = 1e-3


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rt_apex(match: dict[str, Any]) -> float | None:
    meta = _json_object(match.get("extra_metadata"))
    return _as_float(match.get("retention_time")) or _as_float(meta.get("rt_apex"))


def _precursor_mz(match: dict[str, Any]) -> float | None:
    return _as_float(match.get("precursor_mz"))


def isolation_window_contains(spec: dict[str, Any], precursor_mz: float) -> bool:
    precursor = spec.get("precursor") or {}
    target = _as_float(precursor.get("target_mz")) or _as_float(precursor.get("isolation_target_mz"))
    lower = _as_float(precursor.get("lower_offset")) or _as_float(precursor.get("isolation_lower")) or 0.0
    upper = _as_float(precursor.get("upper_offset")) or _as_float(precursor.get("isolation_upper")) or 0.0
    if target is None:
        selected = _as_float(precursor.get("selected_mz"))
        if selected is None:
            return False
        return abs(selected - precursor_mz) <= 2.0
    return (
        target - lower - DIA_ISOLATION_WINDOW_MZ_TOLERANCE
        <= precursor_mz
        <= target + upper + DIA_ISOLATION_WINDOW_MZ_TOLERANCE
    )


def resolve_ms2_scan_at_rt(
    match: dict[str, Any],
    run_spectra: dict[int, dict[str, Any]],
    rt_minutes: float,
    *,
    max_delta_minutes: float | None = None,
) -> int:
    """Resolve the nearest MS2 scan at RT within the match's DIA isolation window."""
    precursor_mz = _precursor_mz(match)
    if precursor_mz is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms2_scan_not_found_for_rt",
                "match_id": match.get("match_id"),
                "rt": rt_minutes,
                "precursor_mz": precursor_mz,
            },
        )

    candidates: list[tuple[float, int]] = []
    for spec_scan, spec in run_spectra.items():
        if int(spec.get("ms_level") or 1) != 2:
            continue
        spec_rt = _as_float(spec.get("rt_seconds"))
        if spec_rt is None:
            continue
        delta = abs(spec_rt / 60.0 - rt_minutes)
        if max_delta_minutes is not None and delta > max_delta_minutes:
            continue
        if not isolation_window_contains(spec, precursor_mz):
            continue
        candidates.append((delta, int(spec_scan)))

    if not candidates:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms2_scan_not_found_for_rt",
                "match_id": match.get("match_id"),
                "rt": rt_minutes,
                "precursor_mz": precursor_mz,
            },
        )
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def resolve_ms2_scan(match: dict[str, Any], run_spectra: dict[int, dict[str, Any]]) -> int:
    """Resolve scan by stored scan first, then by RT and isolation window."""
    meta = _json_object(match.get("extra_metadata"))
    for key in ("resolved_scan", "ms2_scan"):
        scan = _as_int(meta.get(key))
        if scan is not None and (run_spectra.get(scan) or {}).get("ms_level") == 2:
            return scan

    scan = _as_int(match.get("scan_number"))
    if scan is not None and (run_spectra.get(scan) or {}).get("ms_level") == 2:
        return scan

    rt_apex = _rt_apex(match)
    precursor_mz = _precursor_mz(match)
    if rt_apex is None or precursor_mz is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms2_scan_not_found",
                "match_id": match.get("match_id"),
                "rt_apex": rt_apex,
                "precursor_mz": precursor_mz,
            },
        )

    try:
        return resolve_ms2_scan_at_rt(match, run_spectra, rt_apex, max_delta_minutes=0.5)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms2_scan_not_found",
                "match_id": match.get("match_id"),
                "rt_apex": rt_apex,
                "precursor_mz": precursor_mz,
            },
        ) from exc


def resolve_ms1_scan(match: dict[str, Any], run_spectra: dict[int, dict[str, Any]]) -> int:
    """Resolve the closest useful MS1 scan around the match RT apex."""
    rt_apex = _rt_apex(match)
    if rt_apex is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms1_scan_not_found",
                "match_id": match.get("match_id"),
                "rt_apex": rt_apex,
            },
        )

    candidates: list[tuple[float, float, int]] = []
    for spec_scan, spec in run_spectra.items():
        if int(spec.get("ms_level") or 1) != 1:
            continue
        spec_rt = _as_float(spec.get("rt_seconds"))
        if spec_rt is None:
            continue
        spec_rt_min = spec_rt / 60.0
        delta = abs(spec_rt_min - rt_apex)
        if delta > 0.25:
            continue
        tic = sum(float(value) for value in (spec.get("intensity") or []) if value is not None)
        candidates.append((-tic, delta, int(spec_scan)))

    if not candidates:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms1_scan_not_found",
                "match_id": match.get("match_id"),
                "rt_apex": rt_apex,
            },
        )
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][2]
