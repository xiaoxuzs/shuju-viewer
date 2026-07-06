"""Dynamic spectra API backed by indexed mzML access."""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.services import chromatogram_summary
from app.schemas import BuChromatogramOut
from app.services.mzml_scan_index import (
    ScanIndexMissingError,
    ScanIndexStaleError,
    ScanIndexUnsupportedError,
    load_scan_index,
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
from app.spectrum_memory import release_dataset


router = APIRouter(tags=["mzml-spectra"])
MAX_CHROMATOGRAM_POINTS = 8000
MAX_SCAN_INDEX_LIMIT = 2000


def _run_row(session: Session, dataset_id: int, run_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT run_id, file_path, run_metadata
            FROM runs
            WHERE dataset_id = :dataset_id AND run_id = :run_id
            """
        ),
        {"dataset_id": dataset_id, "run_id": run_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run_not_found")
    return dict(row)


def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
    metadata = run.get("run_metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _backfill_detail(code: str, dataset_id: int, run_id: int) -> dict[str, str]:
    return {
        "code": code,
        "backfill_command": f"python scripts/backfill_dataset_derived_data.py --dataset-id {dataset_id} --run-id {run_id}",
    }


def _downsample(rt: list[float], intensity: list[float]) -> tuple[list[float], list[float], bool]:
    if len(rt) <= MAX_CHROMATOGRAM_POINTS:
        return rt, intensity, False
    step = len(rt) / MAX_CHROMATOGRAM_POINTS
    indexes = [min(int(i * step), len(rt) - 1) for i in range(MAX_CHROMATOGRAM_POINTS)]
    return [rt[i] for i in indexes], [intensity[i] for i in indexes], True


def _finite_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_min(values: Any) -> float | None:
    finite = [_finite_or_none(value) for value in values]
    finite = [value for value in finite if value is not None]
    return min(finite) if finite else None


def _finite_max(values: Any) -> float | None:
    finite = [_finite_or_none(value) for value in values]
    finite = [value for value in finite if value is not None]
    return max(finite) if finite else None


def _scan_index_summary(index: Any) -> dict[str, Any]:
    ms_level_counts: dict[str, int] = {}
    for level in index.ms_level:
        key = str(int(level))
        ms_level_counts[key] = ms_level_counts.get(key, 0) + 1

    total_scans = int(index.scan_count)
    ms1_count = ms_level_counts.get("1", 0)
    ms2_count = ms_level_counts.get("2", 0)
    return {
        "total_scans": total_scans,
        "ms1_count": ms1_count,
        "ms2_count": ms2_count,
        "other_count": total_scans - ms1_count - ms2_count,
        "ms_level_counts": ms_level_counts,
        "rt_min": _finite_min(index.retention_time),
        "rt_max": _finite_max(index.retention_time),
        "scan_min": int(index.scan_number.min()) if total_scans else None,
        "scan_max": int(index.scan_number.max()) if total_scans else None,
        "max_tic": _finite_max(index.tic),
        "max_bpc": _finite_max(index.bpc),
        "ms2_fraction": (ms2_count / total_scans) if total_scans else None,
        "precursor_linked_ms2_count": sum(
            1
            for level, precursor_mz in zip(index.ms_level, index.precursor_mz)
            if int(level) == 2 and _finite_or_none(precursor_mz) is not None
        ),
    }


@router.get(
    "/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}",
    response_model=dict[str, Any],
)
def mzml_spectrum(
    dataset_id: int,
    run_id: int,
    scan_number: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec, path_committed = get_spectrum_by_scan(session, dataset_id, run_id, scan_number)
    except (RunNotFoundError, MzmlFileNotFoundError, SpectrumNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MzmlMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnsupportedMzmlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except MzmlIndexError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    if path_committed:
        release_dataset(dataset_id)

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        **spec,
    }


@router.get(
    # ``:int`` converters keep this numeric-only so slug requests (e.g. ``dia-shuju``)
    # fall through to the Bottom-Up ``/datasets/{slug}/.../chromatogram`` route.
    "/datasets/{dataset_id:int}/runs/{run_id:int}/chromatogram",
    response_model=BuChromatogramOut,
)
def mzml_run_chromatogram(
    dataset_id: int,
    run_id: int,
    type: str = "tic",
    session: Session = Depends(get_db),
) -> BuChromatogramOut:
    if type not in {"tic", "bpc"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_chromatogram_type")
    run = _run_row(session, dataset_id, run_id)
    metadata = _run_metadata(run)
    raw_format = str(metadata.get("raw_format") or "").lower()
    if raw_format and raw_format != "mzml":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incompatible_run_format")
    try:
        source_path = chromatogram_summary.resolve_run_source_path(run)
        summary = chromatogram_summary.load_summary(
            dataset_id=dataset_id,
            run_id=run_id,
            source_path=source_path,
        )
    except chromatogram_summary.ChromatogramSummaryMissingError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=_backfill_detail("chromatogram_summary_missing", dataset_id, run_id),
        ) from exc
    except (chromatogram_summary.ChromatogramSummaryStaleError, FileNotFoundError) as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=_backfill_detail("chromatogram_summary_stale", dataset_id, run_id),
        ) from exc

    rt = summary.rt
    intensity = summary.tic if type == "tic" else summary.bpc
    rt, intensity, downsampled = _downsample(rt, intensity)
    return BuChromatogramOut(
        type=type,  # type: ignore[arg-type]
        rt=rt,
        intensity=intensity,
        downsampled=downsampled,
        point_count_original=summary.points_count,
    )


@router.get("/datasets/{dataset_id}/runs/{run_id}/scan-index", response_model=dict[str, Any])
def mzml_run_scan_index(
    dataset_id: int,
    run_id: int,
    ms_level: int | None = None,
    offset: int = 0,
    limit: int = 500,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if ms_level is not None and ms_level not in {1, 2}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_ms_level")
    if offset < 0 or limit <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_pagination")
    limit = min(limit, MAX_SCAN_INDEX_LIMIT)
    try:
        index = load_scan_index(session, dataset_id, run_id)
    except ScanIndexMissingError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=_backfill_detail("scan_index_missing", dataset_id, run_id),
        ) from exc
    except ScanIndexStaleError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=_backfill_detail("scan_index_stale", dataset_id, run_id),
        ) from exc
    except (ScanIndexUnsupportedError, RunNotFoundError, MzmlFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    positions = range(index.scan_count)
    if ms_level is not None:
        positions = [pos for pos in positions if int(index.ms_level[pos]) == ms_level]
    else:
        positions = list(positions)
    total = len(positions)
    page_positions = positions[offset : offset + limit]
    items = [
        {
            "scan_number": int(index.scan_number[pos]),
            "native_id": str(index.native_id[pos]),
            "ms_level": int(index.ms_level[pos]),
            "retention_time": float(index.retention_time[pos]),
            "tic": float(index.tic[pos]),
            "bpc": float(index.bpc[pos]),
            "precursor_mz": _finite_or_none(index.precursor_mz[pos]),
            "isolation_target_mz": _finite_or_none(index.isolation_target_mz[pos]),
            "isolation_lower_mz": _finite_or_none(index.isolation_lower_mz[pos]),
            "isolation_upper_mz": _finite_or_none(index.isolation_upper_mz[pos]),
        }
        for pos in page_positions
    ]
    return {
        "dataset_id": dataset_id,
        "run_id": run_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
        "scans": items,
        "summary": _scan_index_summary(index),
    }
