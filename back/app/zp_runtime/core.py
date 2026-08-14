"""Core spectrum and chromatogram access backed by committed .zp artifacts."""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.mzml_scan_index import MzmlScanIndex
from app.zp_runtime.assets import ActiveZpAsset, find_active_asset
from app.zp_runtime.package import BinaryLayerUnavailableError, zp_read_error_classes
from app.zp_runtime.reader_cache import (
    ZpFileIdentity,
    ZpReaderCacheError,
    ZpReaderHandle,
    clear_reader_cache,
    get_reader_handle,
)


class ZpRuntimeError(RuntimeError):
    pass


class ZpAssetReadError(ZpRuntimeError):
    pass


class ZpRunNotFoundError(ZpRuntimeError):
    pass


class ZpRunMappingError(ZpRuntimeError):
    pass


class ZpSpectrumNotFoundError(ZpRuntimeError):
    pass


class ZpChromatogramNotFoundError(ZpRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ZpChromatogramTrace:
    rt: list[float]
    intensity: list[float]
    point_count_original: int


@dataclass(frozen=True, slots=True)
class _CoreIndex:
    runs: tuple[Any, ...]
    spectra: tuple[Any, ...]
    precursors_by_id: dict[str, Any]
    chromatograms: tuple[Any, ...]
    metadata_by_spectrum_id: dict[str, dict[str, Any]]
    spectra_by_run_id: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    spectra_by_run_scan: dict[tuple[str, int], str] = field(default_factory=dict)
    duplicate_scan_keys: set[tuple[str, int]] = field(default_factory=set)
    chromatogram_by_run_type: dict[tuple[str, str], str] = field(default_factory=dict)


_T = TypeVar("_T")
_SCAN_RE = re.compile(r"(?:^|[\s;])(?:scan|index)=(\d+)(?=$|[\s;])")
_CACHE_LOCK = threading.RLock()
_CORE_INDEX_CACHE: dict[ZpFileIdentity, _CoreIndex] = {}
_SCAN_INDEX_CACHE: dict[tuple[ZpFileIdentity, str], MzmlScanIndex] = {}


def clear_zp_runtime_caches() -> None:
    with _CACHE_LOCK:
        _CORE_INDEX_CACHE.clear()
        _SCAN_INDEX_CACHE.clear()
    clear_reader_cache()


def get_binary_spectrum_by_scan(
    session: Session,
    dataset_id: int,
    run_id: int,
    scan_number: int,
) -> dict[str, Any] | None:
    asset = find_active_asset(session, dataset_id, run_id=run_id)
    if asset is None:
        return None
    handle = _reader_handle(asset)
    index = _core_index(handle)
    zp_run_id = _resolve_zp_run_id(session, dataset_id, run_id, asset, index)
    scan_key = (zp_run_id, int(scan_number))
    if scan_key in index.duplicate_scan_keys:
        raise ZpRunMappingError("binary_scan_mapping_ambiguous")
    spectrum_id = index.spectra_by_run_scan.get(scan_key)
    if spectrum_id is None:
        raise ZpSpectrumNotFoundError("scan_not_found_in_binary")

    def read() -> tuple[Any, Any, Any]:
        with handle.lock:
            return handle.reader.read_spectrum_arrays(spectrum_id)

    spectrum, mz_array, intensity_array = _read_or_raise(read)
    return _spectrum_payload(spectrum, mz_array, intensity_array, index)


def get_binary_scan_index(
    session: Session,
    dataset_id: int,
    run_id: int,
) -> MzmlScanIndex | None:
    asset = find_active_asset(session, dataset_id, run_id=run_id)
    if asset is None:
        return None
    handle = _reader_handle(asset)
    core_index = _core_index(handle)
    zp_run_id = _resolve_zp_run_id(session, dataset_id, run_id, asset, core_index)
    cache_key = (handle.identity, zp_run_id)
    with _CACHE_LOCK:
        cached = _SCAN_INDEX_CACHE.get(cache_key)
        if cached is not None:
            return cached
    built = _build_scan_index(handle, core_index, zp_run_id)
    with _CACHE_LOCK:
        _SCAN_INDEX_CACHE[cache_key] = built
    return built


def get_binary_chromatogram(
    session: Session,
    dataset_id: int,
    run_id: int,
    chrom_type: str,
) -> ZpChromatogramTrace | None:
    asset = find_active_asset(session, dataset_id, run_id=run_id)
    if asset is None:
        return None
    if chrom_type not in {"tic", "bpc"}:
        raise ZpChromatogramNotFoundError("invalid_chromatogram_type")
    handle = _reader_handle(asset)
    index = _core_index(handle)
    zp_run_id = _resolve_zp_run_id(session, dataset_id, run_id, asset, index)
    chromatogram_id = index.chromatogram_by_run_type.get((zp_run_id, chrom_type))
    if chromatogram_id is not None:
        return _read_chromatogram_trace(handle, chromatogram_id)
    return _derive_chromatogram_from_ms1(handle, index, zp_run_id, chrom_type)


def _reader_handle(asset: ActiveZpAsset) -> ZpReaderHandle:
    try:
        return get_reader_handle(asset.zp_path)
    except ZpReaderCacheError as exc:
        raise ZpAssetReadError(str(exc)) from exc


def _core_index(handle: ZpReaderHandle) -> _CoreIndex:
    with _CACHE_LOCK:
        cached = _CORE_INDEX_CACHE.get(handle.identity)
        if cached is not None:
            return cached

    def read() -> _CoreIndex:
        with handle.lock:
            return _build_core_index(
                runs=tuple(handle.reader.read_runs()),
                spectra=tuple(handle.reader.read_spectra()),
                precursors=tuple(handle.reader.read_precursors()),
                chromatograms=tuple(handle.reader.read_chromatograms()),
                extensions=tuple(handle.reader.read_extensions()),
            )

    built = _read_or_raise(read)
    with _CACHE_LOCK:
        _CORE_INDEX_CACHE[handle.identity] = built
    return built


def _build_core_index(
    *,
    runs: tuple[Any, ...],
    spectra: tuple[Any, ...],
    precursors: tuple[Any, ...],
    chromatograms: tuple[Any, ...],
    extensions: tuple[Any, ...],
) -> _CoreIndex:
    spectra_by_run_lists: dict[str, list[Any]] = {}
    spectra_by_run_scan: dict[tuple[str, int], str] = {}
    duplicate_scan_keys: set[tuple[str, int]] = set()
    for spectrum in spectra:
        run_id = str(spectrum.run_id)
        spectra_by_run_lists.setdefault(run_id, []).append(spectrum)
        scan_key = (run_id, int(spectrum.scan_number))
        if scan_key in spectra_by_run_scan:
            duplicate_scan_keys.add(scan_key)
        else:
            spectra_by_run_scan[scan_key] = str(spectrum.spectrum_id)

    chromatogram_by_run_type: dict[tuple[str, str], str] = {}
    for chromatogram in chromatograms:
        key = (str(chromatogram.run_id), str(chromatogram.chromatogram_type).lower())
        chromatogram_by_run_type.setdefault(key, str(chromatogram.chromatogram_id))

    return _CoreIndex(
        runs=runs,
        spectra=spectra,
        precursors_by_id={str(item.precursor_id): item for item in precursors},
        chromatograms=chromatograms,
        metadata_by_spectrum_id=_metadata_by_spectrum_id(extensions),
        spectra_by_run_id={
            run_id: tuple(items) for run_id, items in spectra_by_run_lists.items()
        },
        spectra_by_run_scan=spectra_by_run_scan,
        duplicate_scan_keys=duplicate_scan_keys,
        chromatogram_by_run_type=chromatogram_by_run_type,
    )


def _metadata_by_spectrum_id(extensions: tuple[Any, ...]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for extension in extensions:
        payload = getattr(extension, "payload", None)
        if not isinstance(payload, dict):
            continue
        records = payload.get("spectra")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            spectrum_id = record.get("spectrum_id")
            if isinstance(spectrum_id, str) and spectrum_id:
                out[spectrum_id] = dict(record)
    return out


def _resolve_zp_run_id(
    session: Session,
    dataset_id: int,
    run_id: int,
    asset: ActiveZpAsset,
    index: _CoreIndex,
) -> str:
    if not index.runs:
        raise ZpRunMappingError("binary_run_missing")
    if asset.run_id == run_id and len(index.runs) == 1:
        return str(index.runs[0].run_id)

    db_run = _db_run_row(session, dataset_id, run_id)
    db_candidates = _db_run_identity_values(db_run)
    matches = [
        str(run.run_id)
        for run in index.runs
        if _zp_run_identity_values(run) & db_candidates
    ]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    if len(unique_matches) > 1:
        raise ZpRunMappingError("binary_run_mapping_ambiguous")
    if len(index.runs) == 1 and _dataset_run_count(session, dataset_id) == 1:
        return str(index.runs[0].run_id)
    raise ZpRunMappingError("binary_run_mapping_missing")


def _db_run_row(session: Session, dataset_id: int, run_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT run_id, file_name, file_path, run_metadata
            FROM runs
            WHERE dataset_id = :dataset_id AND run_id = :run_id
            """
        ),
        {"dataset_id": dataset_id, "run_id": run_id},
    ).mappings().one_or_none()
    if row is None:
        raise ZpRunNotFoundError("run_not_found")
    return dict(row)


def _dataset_run_count(session: Session, dataset_id: int) -> int:
    value = session.execute(
        text("SELECT COUNT(*) FROM runs WHERE dataset_id = :dataset_id"),
        {"dataset_id": dataset_id},
    ).scalar_one()
    return int(value or 0)


def _db_run_identity_values(run: dict[str, Any]) -> set[str]:
    values = {
        str(run.get("run_id") or ""),
        str(run.get("file_name") or ""),
        str(run.get("file_path") or ""),
    }
    metadata = _json_object(run.get("run_metadata"))
    for key in (
        "mzml_file_path",
        "raw_file_path",
        "source_path",
        "diann_run_name",
        "run_name",
    ):
        value = metadata.get(key)
        if isinstance(value, str):
            values.add(value)
    return _identity_variants(values)


def _zp_run_identity_values(run: Any) -> set[str]:
    return _identity_variants(
        {
            str(getattr(run, "run_id", "") or ""),
            str(getattr(run, "source_file", "") or ""),
            str(getattr(run, "run_name", "") or ""),
        }
    )


def _identity_variants(values: set[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        text_value = str(value).strip()
        if not text_value:
            continue
        out.add(_normalize_identity(text_value))
        try:
            path_name = Path(text_value).name
        except (OSError, ValueError):
            path_name = ""
        if path_name:
            out.add(_normalize_identity(path_name))
    return {value for value in out if value}


def _normalize_identity(value: str) -> str:
    return value.replace("\\", "/").strip().casefold()


def _spectrum_payload(
    spectrum: Any,
    mz_array: Any,
    intensity_array: Any,
    index: _CoreIndex,
) -> dict[str, Any]:
    return {
        "scan": int(spectrum.scan_number),
        "native_id": str(spectrum.native_id),
        "ms_level": int(spectrum.ms_level),
        "rt_seconds": float(spectrum.rt),
        "mz": _float_values(mz_array.values),
        "intensity": _float_values(intensity_array.values),
        "precursor": _precursor_payload(spectrum, index),
    }


def _precursor_payload(spectrum: Any, index: _CoreIndex) -> dict[str, Any] | None:
    precursor_id = getattr(spectrum, "precursor_id", None)
    precursor = index.precursors_by_id.get(str(precursor_id)) if precursor_id else None
    metadata = index.metadata_by_spectrum_id.get(str(spectrum.spectrum_id), {})
    selected_mz = _first_finite(
        getattr(precursor, "precursor_mz", None),
        metadata.get("source_selected_ion_mz"),
    )
    charge = _first_int(
        getattr(precursor, "charge", None),
        metadata.get("source_selected_ion_charge"),
    )
    target_mz = _first_finite(
        metadata.get("isolation_window_target_mz"),
        selected_mz,
        _midpoint(
            getattr(precursor, "isolation_lower_mz", None),
            getattr(precursor, "isolation_upper_mz", None),
        ),
    )
    lower_mz = _first_finite(
        getattr(precursor, "isolation_lower_mz", None),
        _offset_to_lower(target_mz, metadata.get("isolation_window_lower_offset")),
    )
    upper_mz = _first_finite(
        getattr(precursor, "isolation_upper_mz", None),
        _offset_to_upper(target_mz, metadata.get("isolation_window_upper_offset")),
    )
    if selected_mz is None and charge is None and target_mz is None and lower_mz is None and upper_mz is None:
        return None
    return {
        "parent_scan": _parse_scan_number(metadata.get("precursor_source_spectrum_ref")),
        "target_mz": target_mz,
        "lower_offset": _absolute_to_lower_offset(target_mz, lower_mz),
        "upper_offset": _absolute_to_upper_offset(target_mz, upper_mz),
        "selected_mz": selected_mz,
        "charge": charge,
        "isolation_target_mz": target_mz,
        "isolation_lower": lower_mz,
        "isolation_upper": upper_mz,
    }


def _build_scan_index(
    handle: ZpReaderHandle,
    index: _CoreIndex,
    zp_run_id: str,
) -> MzmlScanIndex:
    columns: dict[str, list[Any]] = {
        "scan_number": [],
        "native_id": [],
        "ms_level": [],
        "retention_time": [],
        "tic": [],
        "bpc": [],
        "precursor_mz": [],
        "isolation_target_mz": [],
        "isolation_lower_mz": [],
        "isolation_upper_mz": [],
    }
    for spectrum in index.spectra_by_run_id.get(zp_run_id, ()):
        metadata = index.metadata_by_spectrum_id.get(str(spectrum.spectrum_id), {})
        tic = _finite_float(metadata.get("total_ion_current"))
        bpc = _finite_float(metadata.get("base_peak_intensity"))
        if tic is None or bpc is None:
            values = _read_spectrum_intensity_values(handle, str(spectrum.spectrum_id))
            tic = float(sum(values)) if values else 0.0
            bpc = float(max(values)) if values else 0.0
        precursor = _precursor_payload(spectrum, index)
        columns["scan_number"].append(int(spectrum.scan_number))
        columns["native_id"].append(str(spectrum.native_id))
        columns["ms_level"].append(int(spectrum.ms_level))
        columns["retention_time"].append(float(spectrum.rt) / 60.0)
        columns["tic"].append(tic)
        columns["bpc"].append(bpc)
        columns["precursor_mz"].append(_nan_if_none((precursor or {}).get("selected_mz")))
        columns["isolation_target_mz"].append(_nan_if_none((precursor or {}).get("isolation_target_mz")))
        columns["isolation_lower_mz"].append(_nan_if_none((precursor or {}).get("isolation_lower")))
        columns["isolation_upper_mz"].append(_nan_if_none((precursor or {}).get("isolation_upper")))

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


def _read_spectrum_intensity_values(handle: ZpReaderHandle, spectrum_id: str) -> list[float]:
    def read() -> list[float]:
        with handle.lock:
            _spectrum, _mz_array, intensity_array = handle.reader.read_spectrum_arrays(spectrum_id)
            return _float_values(intensity_array.values)

    return _read_or_raise(read)


def _read_chromatogram_trace(handle: ZpReaderHandle, chromatogram_id: str) -> ZpChromatogramTrace:
    def read() -> tuple[Any, Any, Any]:
        with handle.lock:
            return handle.reader.read_chromatogram_arrays(chromatogram_id)

    _chromatogram, time_array, intensity_array = _read_or_raise(read)
    rt = [value / 60.0 for value in _float_values(time_array.values)]
    intensity = _float_values(intensity_array.values)
    return ZpChromatogramTrace(rt=rt, intensity=intensity, point_count_original=len(rt))


def _derive_chromatogram_from_ms1(
    handle: ZpReaderHandle,
    index: _CoreIndex,
    zp_run_id: str,
    chrom_type: str,
) -> ZpChromatogramTrace:
    points: list[tuple[float, float]] = []
    for spectrum in index.spectra_by_run_id.get(zp_run_id, ()):
        if int(spectrum.ms_level) != 1:
            continue
        values = _read_spectrum_intensity_values(handle, str(spectrum.spectrum_id))
        intensity = float(sum(values)) if chrom_type == "tic" else (float(max(values)) if values else 0.0)
        points.append((float(spectrum.rt) / 60.0, intensity))
    if not points:
        raise ZpChromatogramNotFoundError("chromatogram_not_found_in_binary")
    points.sort(key=lambda item: item[0])
    return ZpChromatogramTrace(
        rt=[point[0] for point in points],
        intensity=[point[1] for point in points],
        point_count_original=len(points),
    )


def _read_or_raise(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except ZpRuntimeError:
        raise
    except (BinaryLayerUnavailableError, ZpReaderCacheError) as exc:
        raise ZpAssetReadError(str(exc)) from exc
    except zp_read_error_classes() as exc:
        raise ZpAssetReadError("binary_zp_unreadable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ZpAssetReadError("binary_zp_invalid") from exc


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _float_values(values: Any) -> list[float]:
    return [float(value) for value in values]


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first_finite(*values: Any) -> float | None:
    for value in values:
        parsed = _finite_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        return parsed
    return None


def _midpoint(lower: Any, upper: Any) -> float | None:
    parsed_lower = _finite_float(lower)
    parsed_upper = _finite_float(upper)
    if parsed_lower is None or parsed_upper is None:
        return None
    return (parsed_lower + parsed_upper) / 2.0


def _offset_to_lower(target: float | None, offset: Any) -> float | None:
    parsed = _finite_float(offset)
    return target - parsed if target is not None and parsed is not None else None


def _offset_to_upper(target: float | None, offset: Any) -> float | None:
    parsed = _finite_float(offset)
    return target + parsed if target is not None and parsed is not None else None


def _absolute_to_lower_offset(target: float | None, lower: float | None) -> float | None:
    return target - lower if target is not None and lower is not None else None


def _absolute_to_upper_offset(target: float | None, upper: float | None) -> float | None:
    return upper - target if target is not None and upper is not None else None


def _nan_if_none(value: Any) -> float:
    parsed = _finite_float(value)
    return parsed if parsed is not None else float("nan")


def _parse_scan_number(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _SCAN_RE.search(value)
    return int(match.group(1)) if match else None
