"""Persistent run-level TIC/BPC summaries for Bottom-Up mzML data."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pyteomics import mzml

from app.core.config import settings
from app.services.incoming_path_relocate import try_fix_stale_incoming_absolute_path
from app.spectrum_memory.mzml_spectrum_extract import rt_seconds

SUMMARY_VERSION = 1
SUMMARY_DIR_NAME = ".viewer-derived"


class ChromatogramSummaryError(RuntimeError):
    pass


class ChromatogramSummaryMissingError(ChromatogramSummaryError):
    pass


class ChromatogramSummaryStaleError(ChromatogramSummaryError):
    pass


@dataclass(frozen=True)
class ChromatogramSummary:
    rt: list[float]
    tic: list[float]
    bpc: list[float]
    points_count: int


def _derived_root(derived_root: Path | None) -> Path:
    if derived_root is not None:
        return derived_root.resolve()
    return (settings.resolved_data_root / SUMMARY_DIR_NAME).resolve()


def summary_paths(
    dataset_id: int,
    run_id: int,
    *,
    derived_root: Path | None = None,
) -> tuple[Path, Path]:
    directory = _derived_root(derived_root) / "bu-chromatograms" / str(dataset_id) / str(run_id)
    return directory / "summary-v1.npz", directory / "summary-v1.json"


def normalize_source_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def resolve_run_source_path(run: dict[str, Any]) -> Path:
    metadata = run.get("run_metadata")
    run_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    raw = run_metadata.get("mzml_file_path") or run.get("file_path")
    if not raw:
        raise FileNotFoundError("mzML path is missing from run metadata")
    path = try_fix_stale_incoming_absolute_path(Path(str(raw)))
    if path is None:
        raise FileNotFoundError(f"mzML not found: {raw}")
    return path.resolve()


def calculate_summary_from_spectra(
    spectra: Iterable[dict[str, Any]],
) -> ChromatogramSummary:
    points: list[tuple[float, float, float]] = []
    for spec in spectra:
        if int(spec.get("ms level", spec.get("ms_level", 1)) or 1) != 1:
            continue
        intensity_raw = spec.get("intensity array")
        if intensity_raw is None:
            intensity_raw = spec.get("intensity")
        intensity = np.asarray(intensity_raw if intensity_raw is not None else [], dtype=np.float64)
        rt_min = (
            rt_seconds(spec) / 60.0
            if "scanList" in spec
            else float(spec.get("rt_seconds") or 0.0) / 60.0
        )
        tic = float(intensity.sum()) if intensity.size else 0.0
        bpc = float(intensity.max()) if intensity.size else 0.0
        points.append((rt_min, tic, bpc))

    points.sort(key=lambda item: item[0])
    rt = [point[0] for point in points]
    tic = [point[1] for point in points]
    bpc = [point[2] for point in points]
    return ChromatogramSummary(rt=rt, tic=tic, bpc=bpc, points_count=len(points))


def generate_summary_from_mzml(path: Path) -> ChromatogramSummary:
    source_path = path.resolve()
    with mzml.read(str(source_path)) as reader:
        return calculate_summary_from_spectra(reader)


def write_summary(
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
    summary: ChromatogramSummary,
    derived_root: Path | None = None,
) -> dict[str, Any]:
    resolved_source = source_path.resolve()
    source_stat = resolved_source.stat()
    npz_path, metadata_path = summary_paths(dataset_id, run_id, derived_root=derived_root)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary_npz = npz_path.with_name(f".{npz_path.name}.{token}.tmp")
    temporary_metadata = metadata_path.with_name(f".{metadata_path.name}.{token}.tmp")
    metadata = {
        "version": SUMMARY_VERSION,
        "dataset_id": dataset_id,
        "run_id": run_id,
        "source_path": str(resolved_source),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "points_count": summary.points_count,
        "created_at": datetime.now(UTC).isoformat(),
    }

    try:
        with temporary_npz.open("wb") as handle:
            np.savez_compressed(
                handle,
                rt=np.asarray(summary.rt, dtype=np.float64),
                tic=np.asarray(summary.tic, dtype=np.float64),
                bpc=np.asarray(summary.bpc, dtype=np.float64),
            )
        os.replace(temporary_npz, npz_path)
        temporary_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_metadata, metadata_path)
    finally:
        temporary_npz.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)
    return metadata


def load_summary(
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
    derived_root: Path | None = None,
) -> ChromatogramSummary:
    npz_path, metadata_path = summary_paths(dataset_id, run_id, derived_root=derived_root)
    if not npz_path.is_file() or not metadata_path.is_file():
        raise ChromatogramSummaryMissingError("chromatogram_summary_missing")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        source_stat = source_path.stat()
    except (OSError, ValueError, TypeError) as exc:
        raise ChromatogramSummaryStaleError("chromatogram_summary_stale") from exc

    valid = (
        metadata.get("version") == SUMMARY_VERSION
        and metadata.get("dataset_id") == dataset_id
        and metadata.get("run_id") == run_id
        and os.path.normcase(str(metadata.get("source_path") or ""))
        == normalize_source_path(source_path)
        and metadata.get("source_size") == source_stat.st_size
        and metadata.get("source_mtime_ns") == source_stat.st_mtime_ns
    )
    if not valid:
        raise ChromatogramSummaryStaleError("chromatogram_summary_stale")

    try:
        with np.load(npz_path, allow_pickle=False) as arrays:
            rt = arrays["rt"].astype(np.float64, copy=False).tolist()
            tic = arrays["tic"].astype(np.float64, copy=False).tolist()
            bpc = arrays["bpc"].astype(np.float64, copy=False).tolist()
    except (OSError, ValueError, KeyError) as exc:
        raise ChromatogramSummaryStaleError("chromatogram_summary_stale") from exc

    points_count = int(metadata.get("points_count") or 0)
    if len(rt) != points_count or len(tic) != points_count or len(bpc) != points_count:
        raise ChromatogramSummaryStaleError("chromatogram_summary_stale")
    return ChromatogramSummary(rt=rt, tic=tic, bpc=bpc, points_count=points_count)
