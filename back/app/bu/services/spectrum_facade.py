"""Bottom-Up mzML spectrum facade."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bu.services.theoretical_fragments import match_by_ions
from app.schemas import BuSpectrumMarker, BuSpectrumPrecursor, BuSpectrumV1
from app.services import spectrum_memory_wiring
from app.services.mzml_scan_index import (
    ScanIndexError,
    ScanIndexMissingError,
    ScanIndexStaleError,
    ScanIndexUnsupportedError,
    ScanMetadataNotFoundError,
    find_nearest_ms1_scan,
    find_nearest_ms2_scan,
)
from app.services.mzml_scan_reader import (
    MzmlFileNotFoundError,
    MzmlIndexError,
    MzmlMappingError,
    RunNotFoundError,
    SpectrumNotFoundError,
    UnsupportedMzmlError,
    get_spectrum_by_scan,
)
from app.spectrum_memory import CapacityError, NotResidentError, get_mzml_run_spectra, release_dataset


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _raw_format(match: dict[str, Any]) -> str:
    return str(_json_object(match.get("run_metadata")).get("raw_format") or "").lower()


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rt_apex(match: dict[str, Any]) -> float | None:
    meta = _json_object(match.get("extra_metadata"))
    return _float(match.get("retention_time")) or _float(meta.get("rt_apex"))


def _explicit_ms2_scan(match: dict[str, Any], scan: int | None) -> int | None:
    requested = _positive_int(scan)
    if requested is not None:
        return requested
    meta = _json_object(match.get("extra_metadata"))
    for value in (
        meta.get("resolved_scan"),
        meta.get("ms2_scan"),
        match.get("scan_number"),
    ):
        resolved = _positive_int(value)
        if resolved is not None:
            return resolved
    return None


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


def _get_indexed_spectrum(
    session: Session,
    dataset_id: int,
    run_id: int,
    scan: int,
    *,
    expected_ms_level: int,
    not_found_detail: str,
) -> dict[str, Any]:
    try:
        spec, path_committed = get_spectrum_by_scan(session, dataset_id, run_id, scan)
    except (RunNotFoundError, MzmlFileNotFoundError, SpectrumNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MzmlMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnsupportedMzmlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except MzmlIndexError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    if path_committed:
        release_dataset(dataset_id)
    if int(spec.get("ms_level") or 1) != expected_ms_level:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return spec


def _get_indexed_ms2(
    session: Session,
    dataset_id: int,
    run_id: int,
    scan: int,
) -> dict[str, Any]:
    return _get_indexed_spectrum(
        session,
        dataset_id,
        run_id,
        scan,
        expected_ms_level=2,
        not_found_detail="ms2_scan_not_found",
    )


def _scan_index_error(
    exc: Exception,
    *,
    dataset_id: int,
    run_id: int,
) -> HTTPException:
    command = (
        "python scripts/backfill_mzml_scan_indexes.py "
        f"--dataset-id {dataset_id} --run-id {run_id}"
    )
    if isinstance(exc, ScanIndexMissingError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "scan_index_missing", "backfill_command": command},
        )
    if isinstance(exc, ScanIndexStaleError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "scan_index_stale", "backfill_command": command},
        )
    if isinstance(exc, (RunNotFoundError, MzmlFileNotFoundError)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MzmlMappingError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ScanIndexUnsupportedError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


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


def spectrum_v1(
    spec: dict[str, Any],
    *,
    matched_ions: list[Any] | None = None,
    markers: list[BuSpectrumMarker] | None = None,
) -> BuSpectrumV1:
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
        markers=markers or [],
    )


def get_match_ms2(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
    *,
    ppm: float = 20.0,
    scan: int | None = None,
    rt: float | None = None,
) -> BuSpectrumV1:
    """Return SpectrumV1 for the match's mzML MS2 scan."""
    ensure_mzml_match(match)
    if scan is not None and rt is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="scan_and_rt_are_mutually_exclusive")
    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
    selected_scan = None if rt is not None else _explicit_ms2_scan(match, scan)
    if selected_scan is not None:
        spec = _get_indexed_ms2(session, dataset_id, run_id, selected_scan)
    else:
        rt_target = rt if rt is not None else _rt_apex(match)
        precursor_mz = _float(match.get("precursor_mz"))
        error_name = "ms2_scan_not_found_for_rt" if rt is not None else "ms2_scan_not_found"
        if rt_target is None or precursor_mz is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "error": error_name,
                    "match_id": match.get("match_id"),
                    "rt" if rt is not None else "rt_apex": rt_target,
                    "precursor_mz": precursor_mz,
                },
            )
        try:
            candidate = find_nearest_ms2_scan(
                session,
                dataset_id,
                run_id,
                rt_target,
                precursor_mz,
                max_delta_minutes=None if rt is not None else 0.5,
            )
        except ScanMetadataNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "error": error_name,
                    "match_id": match.get("match_id"),
                    "rt" if rt is not None else "rt_apex": rt_target,
                    "precursor_mz": precursor_mz,
                },
            ) from exc
        except (
            ScanIndexError,
            RunNotFoundError,
            MzmlFileNotFoundError,
            MzmlMappingError,
        ) as exc:
            raise _scan_index_error(exc, dataset_id=dataset_id, run_id=run_id) from exc
        spec = _get_indexed_ms2(session, dataset_id, run_id, candidate.scan_number)
    mz = [float(v) for v in (spec.get("mz") or [])]
    intensity = [float(v) for v in (spec.get("intensity") or [])]
    matched_ions = match_by_ions(
        sequence=str(match.get("sequence") or ""),
        mz=mz,
        intensity=intensity,
        ppm=ppm,
    )
    return spectrum_v1(spec, matched_ions=matched_ions)


def get_match_ms1(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
) -> BuSpectrumV1:
    """Return SpectrumV1 for the match's nearby mzML MS1 scan."""
    ensure_mzml_match(match)
    dataset_id = int(dataset["dataset_id"])
    run_id = int(match["run_id"])
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
    try:
        candidate = find_nearest_ms1_scan(
            session,
            dataset_id,
            run_id,
            rt_apex,
            window_minutes=0.25,
        )
    except ScanMetadataNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ms1_scan_not_found",
                "match_id": match.get("match_id"),
                "rt_apex": rt_apex,
            },
        ) from exc
    except (
        ScanIndexError,
        RunNotFoundError,
        MzmlFileNotFoundError,
        MzmlMappingError,
    ) as exc:
        raise _scan_index_error(exc, dataset_id=dataset_id, run_id=run_id) from exc
    spec = _get_indexed_spectrum(
        session,
        dataset_id,
        run_id,
        candidate.scan_number,
        expected_ms_level=1,
        not_found_detail="ms1_scan_not_found",
    )
    precursor_mz = match.get("precursor_mz")
    charge_raw = match.get("precursor_charge")
    try:
        precursor_charge = int(charge_raw) if charge_raw is not None else None
    except (TypeError, ValueError):
        precursor_charge = None
    markers: list[BuSpectrumMarker] = []
    if precursor_mz is not None:
        markers.append(
            BuSpectrumMarker(
                mz=float(precursor_mz),
                label="precursor",
                charge=precursor_charge,
            )
        )
    spec_with_precursor = {
        **spec,
        "precursor": {
            "selected_mz": precursor_mz,
            "charge": precursor_charge,
        },
    }
    return spectrum_v1(spec_with_precursor, markers=markers)


def spectrum_not_implemented() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")
