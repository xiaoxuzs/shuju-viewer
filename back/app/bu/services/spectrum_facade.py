"""Bottom-Up mzML spectrum facade."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bu.services.scan_resolver import resolve_ms2_scan
from app.bu.services.theoretical_fragments import match_by_ions
from app.schemas import BuSpectrumPrecursor, BuSpectrumV1
from app.services import spectrum_memory_wiring
from app.spectrum_memory import CapacityError, NotResidentError, get_mzml_run_spectra


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _raw_format(match: dict[str, Any]) -> str:
    return str(_json_object(match.get("run_metadata")).get("raw_format") or "").lower()


def ensure_mzml_match(match: dict[str, Any]) -> None:
    if _raw_format(match) != "mzml":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unsupported_raw_format")


def ensure_resident(session: Session, dataset_id: int) -> None:
    try:
        spectrum_memory_wiring.ensure_mzml_dataset_resident(session, dataset_id)
    except CapacityError as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


def get_run_spectra(session: Session, dataset_id: int, run_id: int) -> dict[int, dict[str, Any]]:
    ensure_resident(session, dataset_id)
    try:
        spectra = get_mzml_run_spectra(dataset_id, run_id)
    except NotResidentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="mzml_not_resident") from exc
    if spectra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run_spectra_not_found")
    return spectra


def _precursor_payload(raw: dict[str, Any] | None) -> BuSpectrumPrecursor | None:
    if not isinstance(raw, dict):
        return None
    return BuSpectrumPrecursor(
        selected_mz=raw.get("selected_mz"),
        charge=raw.get("charge"),
        isolation_target_mz=raw.get("target_mz") or raw.get("isolation_target_mz"),
        isolation_lower=raw.get("lower_offset") or raw.get("isolation_lower"),
        isolation_upper=raw.get("upper_offset") or raw.get("isolation_upper"),
    )


def spectrum_v1(spec: dict[str, Any], *, matched_ions: list[Any] | None = None) -> BuSpectrumV1:
    rt_seconds = float(spec.get("rt_seconds") or 0.0)
    return BuSpectrumV1(
        scan=int(spec["scan"]),
        native_id=spec.get("native_id"),
        ms_level=int(spec.get("ms_level") or 1),  # type: ignore[arg-type]
        rt_seconds=rt_seconds,
        rt_minutes=rt_seconds / 60.0,
        mz=[float(v) for v in (spec.get("mz") or [])],
        intensity=[float(v) for v in (spec.get("intensity") or [])],
        precursor=_precursor_payload(spec.get("precursor")),
        matched_ions=matched_ions or [],
    )


def get_match_ms2(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    ppm: float = 20.0,
) -> BuSpectrumV1:
    """Return SpectrumV1 for the match's mzML MS2 scan."""
    ensure_mzml_match(match)
    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
    spectra = get_run_spectra(session, dataset_id, run_id)
    scan = resolve_ms2_scan(match, spectra)
    spec = spectra.get(scan)
    if spec is None or int(spec.get("ms_level") or 1) != 2:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ms2_scan_not_found")
    mz = [float(v) for v in (spec.get("mz") or [])]
    intensity = [float(v) for v in (spec.get("intensity") or [])]
    matched_ions = match_by_ions(
        sequence=str(match.get("sequence") or ""),
        mz=mz,
        intensity=intensity,
        ppm=ppm,
    )
    return spectrum_v1(spec, matched_ions=matched_ions)


def spectrum_not_implemented() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")
