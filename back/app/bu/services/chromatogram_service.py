"""Run-level mzML TIC/BPC service for Bottom-Up overview."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.tdf_reader import chromatogram as tdf_chromatogram
from app.bu.tdf_reader import dia_windows as tdf_dia_windows
from app.bu.tdf_reader.session_cache import TdfpyUnavailable
from app.bu.services.spectrum_facade import get_run_spectra
from app.schemas import BuChromatogramOut, BuDiaWindowsOut

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
    if raw_format != "mzml":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incompatible_run_format")

    spectra = get_run_spectra(session, dataset_id, run_id)
    points: list[tuple[float, float]] = []
    for spec in spectra.values():
        if int(spec.get("ms_level") or 1) != 1:
            continue
        values = [float(v) for v in (spec.get("intensity") or [])]
        if chrom_type == "tic":
            y = sum(values)
        else:
            y = max(values) if values else 0.0
        rt_min = float(spec.get("rt_seconds") or 0.0) / 60.0
        points.append((rt_min, y))
    points.sort(key=lambda item: item[0])
    rt = [p[0] for p in points]
    intensity = [p[1] for p in points]
    original = len(rt)
    rt, intensity, downsampled = _downsample(rt, intensity)
    return BuChromatogramOut(
        type=chrom_type,
        rt=rt,
        intensity=intensity,
        downsampled=downsampled,
        point_count_original=original,
    )


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
