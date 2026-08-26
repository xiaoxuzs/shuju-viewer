"""Run-level mzML TIC/BPC service for Bottom-Up overview."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.tdf_reader import chromatogram as tdf_chromatogram
from app.bu.tdf_reader import dia_windows as tdf_dia_windows
from app.bu.tdf_reader.session_cache import TdfpyUnavailable
from app.bu.services import chromatogram_summary
from app.schemas import BuChromatogramOut, BuDiaWindowsOut
from app.zp_runtime import (
    ZpAssetReadError,
    ZpChromatogramNotFoundError,
    ZpRunMappingError,
    ZpRunNotFoundError,
    get_binary_chromatogram,
)

MAX_POINTS = 8000


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


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


def _has_mzml_source(run_metadata: dict[str, Any]) -> bool:
    raw_format = str(run_metadata.get("raw_format") or "").lower()
    return raw_format == "mzml" or bool(run_metadata.get("mzml_file_path"))


def _downsample(rt: list[float], intensity: list[float]) -> tuple[list[float], list[float], bool]:
    if len(rt) <= MAX_POINTS:
        return rt, intensity, False
    step = len(rt) / MAX_POINTS
    indexes = [min(int(i * step), len(rt) - 1) for i in range(MAX_POINTS)]
    return [rt[i] for i in indexes], [intensity[i] for i in indexes], True


def get_chromatogram(
    session: Session,
    dataset: dict[str, Any],
    run_id: int,
    *,
    chrom_type: Literal["tic", "bpc"],
) -> BuChromatogramOut:
    if chrom_type not in {"tic", "bpc"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_chromatogram_type",
        )
    dataset_id = int(dataset["dataset_id"])
    run = _run_row(session, dataset_id, run_id)
    run_meta = _json_object(run.get("run_metadata"))
    raw_format = str(run_meta.get("raw_format") or "").lower()
    if raw_format == "bruker_d":
        try:
            return tdf_chromatogram.get_chromatogram(dataset_id=dataset_id, run=run, chrom_type=chrom_type)
        except TdfpyUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="tdfpy_unavailable") from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc) or "tdf_not_found") from exc

    summary_error: Exception | None = None
    has_mzml_source = _has_mzml_source(run_meta)
    if has_mzml_source:
        try:
            source_path = chromatogram_summary.resolve_run_source_path(run)
            summary = chromatogram_summary.load_summary(
                dataset_id=dataset_id,
                run_id=run_id,
                source_path=source_path,
            )
        except (
            chromatogram_summary.ChromatogramSummaryMissingError,
            chromatogram_summary.ChromatogramSummaryStaleError,
            FileNotFoundError,
        ) as exc:
            summary_error = exc
        else:
            rt = summary.rt
            intensity = summary.tic if chrom_type == "tic" else summary.bpc
            original = summary.points_count
            rt, intensity, downsampled = _downsample(rt, intensity)
            return BuChromatogramOut(
                type=chrom_type,
                rt=rt,
                intensity=intensity,
                downsampled=downsampled,
                point_count_original=original,
            )

    try:
        binary_trace = get_binary_chromatogram(session, dataset_id, run_id, chrom_type)
    except ZpRunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run_not_found") from exc
    except ZpChromatogramNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ZpRunMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ZpAssetReadError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if binary_trace is not None:
        rt, intensity, downsampled = _downsample(binary_trace.rt, binary_trace.intensity)
        return BuChromatogramOut(
            type=chrom_type,
            rt=rt,
            intensity=intensity,
            downsampled=downsampled,
            point_count_original=binary_trace.point_count_original,
        )

    if not has_mzml_source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incompatible_run_format")
    if isinstance(summary_error, chromatogram_summary.ChromatogramSummaryMissingError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="chromatogram_summary_missing",
        ) from summary_error
    if isinstance(summary_error, (chromatogram_summary.ChromatogramSummaryStaleError, FileNotFoundError)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="chromatogram_summary_stale",
        ) from summary_error

    raise HTTPException(status.HTTP_409_CONFLICT, detail="chromatogram_summary_missing")


def get_dia_windows(session: Session, dataset: dict[str, Any], run_id: int) -> BuDiaWindowsOut:
    dataset_id = int(dataset["dataset_id"])
    run = _run_row(session, dataset_id, run_id)
    run_meta = _json_object(run.get("run_metadata"))
    if str(run_meta.get("raw_format") or "").lower() != "bruker_d":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incompatible_run_format")
    try:
        return tdf_dia_windows.get_dia_windows(dataset_id=dataset_id, run=run)
    except TdfpyUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="tdfpy_unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc) or "tdf_not_found") from exc


def unsupported() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")
