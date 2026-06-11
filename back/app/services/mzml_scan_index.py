"""Persistent lightweight scan metadata indexes for mzML runs."""

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
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.mzml_scan_reader import (
    RunNotFoundError,
    parse_native_scan_number,
    resolve_run_mzml_path,
)
from app.spectrum_memory.mzml_spectrum_extract import extract_precursor, rt_seconds

INDEX_VERSION = 1
DERIVED_DIR_NAME = ".viewer-derived"
INDEX_FIELDS = (
    "scan_number",
    "native_id",
    "ms_level",
    "retention_time",
    "tic",
    "bpc",
    "precursor_mz",
    "isolation_target_mz",
    "isolation_lower_mz",
    "isolation_upper_mz",
)


class ScanIndexError(RuntimeError):
    pass


class ScanIndexMissingError(ScanIndexError):
    pass


class ScanIndexStaleError(ScanIndexError):
    pass


class ScanIndexUnsupportedError(ScanIndexError):
    pass


class ScanMetadataNotFoundError(ScanIndexError):
    pass


@dataclass(frozen=True)
class ScanMetadata:
    scan_number: int
    native_id: str
    ms_level: int
    retention_time: float
    tic: float
    bpc: float
    precursor_mz: float | None
    isolation_target_mz: float | None
    isolation_lower_mz: float | None
    isolation_upper_mz: float | None


@dataclass(frozen=True)
class MzmlScanIndex:
    scan_number: np.ndarray
    native_id: np.ndarray
    ms_level: np.ndarray
    retention_time: np.ndarray
    tic: np.ndarray
    bpc: np.ndarray
    precursor_mz: np.ndarray
    isolation_target_mz: np.ndarray
    isolation_lower_mz: np.ndarray
    isolation_upper_mz: np.ndarray

    @property
    def scan_count(self) -> int:
        return int(self.scan_number.size)


def _derived_root(derived_root: Path | None) -> Path:
    if derived_root is not None:
        return derived_root.resolve()
    return (settings.resolved_data_root / DERIVED_DIR_NAME).resolve()


def scan_index_paths(
    dataset_id: int,
    run_id: int,
    *,
    derived_root: Path | None = None,
) -> tuple[Path, Path]:
    directory = _derived_root(derived_root) / "mzml-scan-index" / str(dataset_id) / str(run_id)
    return directory / "scan-index-v1.npz", directory / "scan-index-v1.json"


def normalize_source_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _optional_float(value: Any) -> float:
    try:
        return float(value) if value is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def build_scan_index_from_spectra(spectra: Iterable[dict[str, Any]]) -> MzmlScanIndex:
    columns: dict[str, list[Any]] = {field: [] for field in INDEX_FIELDS}
    native_id_by_scan: dict[int, str] = {}
    for spec in spectra:
        native_id = str(spec.get("id") or "")
        scan_number = parse_native_scan_number(native_id)
        if scan_number is None:
            raise ScanIndexUnsupportedError(f"cannot parse scan number from native_id: {native_id!r}")
        existing_native_id = native_id_by_scan.get(scan_number)
        if existing_native_id is not None and existing_native_id != native_id:
            raise ScanIndexUnsupportedError(
                f"multiple native IDs map to scan number {scan_number}: "
                f"{existing_native_id!r}, {native_id!r}"
            )
        native_id_by_scan[scan_number] = native_id

        intensity_raw = spec.get("intensity array")
        if intensity_raw is None:
            intensity_raw = spec.get("intensity")
        intensity = np.asarray(intensity_raw if intensity_raw is not None else [], dtype=np.float64)
        precursor = extract_precursor(spec)
        target_mz = _optional_float((precursor or {}).get("target_mz"))
        lower_offset = _optional_float((precursor or {}).get("lower_offset"))
        upper_offset = _optional_float((precursor or {}).get("upper_offset"))
        lower_mz = target_mz - lower_offset if np.isfinite(target_mz) and np.isfinite(lower_offset) else np.nan
        upper_mz = target_mz + upper_offset if np.isfinite(target_mz) and np.isfinite(upper_offset) else np.nan

        columns["scan_number"].append(scan_number)
        columns["native_id"].append(native_id)
        columns["ms_level"].append(int(spec.get("ms level", spec.get("ms_level", 1)) or 1))
        columns["retention_time"].append(rt_seconds(spec) / 60.0)
        columns["tic"].append(float(intensity.sum()) if intensity.size else 0.0)
        columns["bpc"].append(float(intensity.max()) if intensity.size else 0.0)
        columns["precursor_mz"].append(_optional_float((precursor or {}).get("selected_mz")))
        columns["isolation_target_mz"].append(target_mz)
        columns["isolation_lower_mz"].append(lower_mz)
        columns["isolation_upper_mz"].append(upper_mz)

    return MzmlScanIndex(
        scan_number=np.asarray(columns["scan_number"], dtype=np.int64),
        native_id=np.asarray(columns["native_id"], dtype=np.str_),
        ms_level=np.asarray(columns["ms_level"], dtype=np.uint8),
        retention_time=np.asarray(columns["retention_time"], dtype=np.float64),
        tic=np.asarray(columns["tic"], dtype=np.float64),
        bpc=np.asarray(columns["bpc"], dtype=np.float64),
        precursor_mz=np.asarray(columns["precursor_mz"], dtype=np.float64),
        isolation_target_mz=np.asarray(columns["isolation_target_mz"], dtype=np.float64),
        isolation_lower_mz=np.asarray(columns["isolation_lower_mz"], dtype=np.float64),
        isolation_upper_mz=np.asarray(columns["isolation_upper_mz"], dtype=np.float64),
    )


def generate_scan_index_from_mzml(path: Path) -> MzmlScanIndex:
    source_path = path.resolve()
    lower_name = source_path.name.lower()
    if lower_name.endswith((".mzml.gz", ".mzml.gzip")):
        raise ScanIndexUnsupportedError("gzip-compressed mzML scan indexes are not supported")
    if not lower_name.endswith(".mzml"):
        raise ScanIndexUnsupportedError(f"not an mzML file: {source_path}")
    with mzml.read(str(source_path)) as reader:
        return build_scan_index_from_spectra(reader)


def write_scan_index(
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
    index: MzmlScanIndex,
    derived_root: Path | None = None,
) -> dict[str, Any]:
    resolved_source = source_path.resolve()
    source_stat = resolved_source.stat()
    npz_path, metadata_path = scan_index_paths(dataset_id, run_id, derived_root=derived_root)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary_npz = npz_path.with_name(f".{npz_path.name}.{token}.tmp")
    temporary_metadata = metadata_path.with_name(f".{metadata_path.name}.{token}.tmp")
    metadata = {
        "version": INDEX_VERSION,
        "dataset_id": dataset_id,
        "run_id": run_id,
        "source_path": str(resolved_source),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "scan_count": index.scan_count,
        "ms1_count": int(np.count_nonzero(index.ms_level == 1)),
        "ms2_count": int(np.count_nonzero(index.ms_level == 2)),
        "created_at": datetime.now(UTC).isoformat(),
        "fields": list(INDEX_FIELDS),
        "retention_time_unit": "min",
    }
    try:
        with temporary_npz.open("wb") as handle:
            np.savez_compressed(
                handle,
                **{field: getattr(index, field) for field in INDEX_FIELDS},
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


def _resolve_source_path(session: Session, dataset_id: int, run_id: int) -> Path:
    row = session.execute(
        text(
            """
            SELECT run_metadata
            FROM runs
            WHERE dataset_id = :dataset_id AND run_id = :run_id
            """
        ),
        {"dataset_id": dataset_id, "run_id": run_id},
    ).mappings().one_or_none()
    if row is None:
        raise RunNotFoundError("run not found")
    metadata = row.get("run_metadata")
    run_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    raw_format = str(run_metadata.get("raw_format") or "").lower()
    if raw_format and raw_format != "mzml":
        raise ScanIndexUnsupportedError("run is not mzML")
    source_path, _path_committed = resolve_run_mzml_path(session, dataset_id, run_id)
    return source_path


def load_scan_index(
    session: Session,
    dataset_id: int,
    run_id: int,
    *,
    derived_root: Path | None = None,
) -> MzmlScanIndex:
    source_path = _resolve_source_path(session, dataset_id, run_id)
    npz_path, metadata_path = scan_index_paths(dataset_id, run_id, derived_root=derived_root)
    if not npz_path.is_file() or not metadata_path.is_file():
        raise ScanIndexMissingError("scan_index_missing")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        source_stat = source_path.stat()
        metadata_source_path = normalize_source_path(Path(str(metadata["source_path"])))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ScanIndexStaleError("scan_index_stale") from exc
    valid = (
        metadata.get("version") == INDEX_VERSION
        and metadata.get("dataset_id") == dataset_id
        and metadata.get("run_id") == run_id
        and metadata_source_path == normalize_source_path(source_path)
        and metadata.get("source_size") == source_stat.st_size
        and metadata.get("source_mtime_ns") == source_stat.st_mtime_ns
        and metadata.get("fields") == list(INDEX_FIELDS)
        and metadata.get("retention_time_unit") == "min"
    )
    if not valid:
        raise ScanIndexStaleError("scan_index_stale")

    try:
        with np.load(npz_path, allow_pickle=False) as arrays:
            index = MzmlScanIndex(
                **{field: arrays[field].copy() for field in INDEX_FIELDS},
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ScanIndexStaleError("scan_index_stale") from exc
    if any(getattr(index, field).ndim != 1 for field in INDEX_FIELDS):
        raise ScanIndexStaleError("scan_index_stale")
    if any(getattr(index, field).size != index.scan_count for field in INDEX_FIELDS):
        raise ScanIndexStaleError("scan_index_stale")
    if int(metadata.get("scan_count") or -1) != index.scan_count:
        raise ScanIndexStaleError("scan_index_stale")
    return index


def _optional_value(value: np.floating[Any]) -> float | None:
    parsed = float(value)
    return parsed if np.isfinite(parsed) else None


def _metadata_at(index: MzmlScanIndex, position: int) -> ScanMetadata:
    return ScanMetadata(
        scan_number=int(index.scan_number[position]),
        native_id=str(index.native_id[position]),
        ms_level=int(index.ms_level[position]),
        retention_time=float(index.retention_time[position]),
        tic=float(index.tic[position]),
        bpc=float(index.bpc[position]),
        precursor_mz=_optional_value(index.precursor_mz[position]),
        isolation_target_mz=_optional_value(index.isolation_target_mz[position]),
        isolation_lower_mz=_optional_value(index.isolation_lower_mz[position]),
        isolation_upper_mz=_optional_value(index.isolation_upper_mz[position]),
    )


def find_scan_by_number(
    session: Session,
    dataset_id: int,
    run_id: int,
    scan_number: int,
    *,
    derived_root: Path | None = None,
) -> ScanMetadata:
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    positions = np.flatnonzero(index.scan_number == scan_number)
    if positions.size == 0:
        raise ScanMetadataNotFoundError(f"scan_not_found: {scan_number}")
    return _metadata_at(index, int(positions[0]))


def find_nearest_ms1_scan(
    session: Session,
    dataset_id: int,
    run_id: int,
    rt: float,
    window_minutes: float = 0.25,
    *,
    derived_root: Path | None = None,
) -> ScanMetadata:
    if window_minutes < 0:
        raise ValueError("window_minutes must be non-negative")
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    distance = np.abs(index.retention_time - float(rt))
    positions = np.flatnonzero((index.ms_level == 1) & (distance <= window_minutes))
    if positions.size == 0:
        raise ScanMetadataNotFoundError("ms1_scan_not_found")
    order = np.lexsort(
        (
            index.scan_number[positions],
            distance[positions],
            -index.tic[positions],
        )
    )
    return _metadata_at(index, int(positions[int(order[0])]))


def find_ms1_scans_in_rt_range(
    session: Session,
    dataset_id: int,
    run_id: int,
    rt_start: float,
    rt_end: float,
    *,
    derived_root: Path | None = None,
) -> list[ScanMetadata]:
    if rt_start > rt_end:
        raise ValueError("rt_start must be less than or equal to rt_end")
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    positions = np.flatnonzero(
        (index.ms_level == 1)
        & (index.retention_time >= rt_start)
        & (index.retention_time <= rt_end)
    )
    order = np.lexsort((index.scan_number[positions], index.retention_time[positions]))
    return [_metadata_at(index, int(positions[int(item)])) for item in order]


def find_ms2_scans_in_rt_range(
    session: Session,
    dataset_id: int,
    run_id: int,
    rt_start: float,
    rt_end: float,
    *,
    derived_root: Path | None = None,
) -> list[ScanMetadata]:
    if rt_start > rt_end:
        raise ValueError("rt_start must be less than or equal to rt_end")
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    positions = np.flatnonzero(
        (index.ms_level == 2)
        & (index.retention_time >= rt_start)
        & (index.retention_time <= rt_end)
    )
    if positions.size == 0:
        raise ScanMetadataNotFoundError("ms2_scans_not_found")
    order = np.lexsort((index.scan_number[positions], index.retention_time[positions]))
    return [_metadata_at(index, int(positions[int(item)])) for item in order]


def find_ms2_scans_by_rt_and_isolation(
    session: Session,
    dataset_id: int,
    run_id: int,
    rt_start: float,
    rt_end: float,
    precursor_mz: float,
    tolerance: float,
    *,
    derived_root: Path | None = None,
) -> list[ScanMetadata]:
    if rt_start > rt_end:
        raise ValueError("rt_start must be less than or equal to rt_end")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    positions = np.flatnonzero(
        (index.ms_level == 2)
        & (index.retention_time >= rt_start)
        & (index.retention_time <= rt_end)
        & np.isfinite(index.isolation_lower_mz)
        & np.isfinite(index.isolation_upper_mz)
        & (float(precursor_mz) >= index.isolation_lower_mz - tolerance)
        & (float(precursor_mz) <= index.isolation_upper_mz + tolerance)
    )
    if positions.size == 0:
        raise ScanMetadataNotFoundError("ms2_scans_not_found")
    order = np.lexsort((index.scan_number[positions], index.retention_time[positions]))
    return [_metadata_at(index, int(positions[int(item)])) for item in order]


def find_nearest_ms2_scan(
    session: Session,
    dataset_id: int,
    run_id: int,
    rt: float,
    precursor_mz: float,
    *,
    max_delta_minutes: float | None = None,
    derived_root: Path | None = None,
) -> ScanMetadata:
    """Find the nearest MS2 matching the legacy isolation-window semantics."""
    if max_delta_minutes is not None and max_delta_minutes < 0:
        raise ValueError("max_delta_minutes must be non-negative")
    index = load_scan_index(session, dataset_id, run_id, derived_root=derived_root)
    distance = np.abs(index.retention_time - float(rt))
    target_present = np.isfinite(index.isolation_target_mz)
    lower_bound = np.where(
        np.isfinite(index.isolation_lower_mz),
        index.isolation_lower_mz,
        index.isolation_target_mz,
    )
    upper_bound = np.where(
        np.isfinite(index.isolation_upper_mz),
        index.isolation_upper_mz,
        index.isolation_target_mz,
    )
    isolation_match = target_present & (precursor_mz >= lower_bound) & (precursor_mz <= upper_bound)
    selected_match = (
        ~target_present
        & np.isfinite(index.precursor_mz)
        & (np.abs(index.precursor_mz - float(precursor_mz)) <= 2.0)
    )
    mask = (index.ms_level == 2) & (isolation_match | selected_match)
    if max_delta_minutes is not None:
        mask &= distance <= max_delta_minutes
    positions = np.flatnonzero(mask)
    if positions.size == 0:
        raise ScanMetadataNotFoundError("ms2_scan_not_found")
    order = np.lexsort((index.scan_number[positions], distance[positions]))
    return _metadata_at(index, int(positions[int(order[0])]))
