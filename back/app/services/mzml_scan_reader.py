"""Read one spectrum from an indexed mzML without loading the whole run."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from pyteomics import mzml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.incoming_path_relocate import try_fix_stale_incoming_absolute_path
from app.services.mzml_mapping import (
    build_mapping_from_extracted_dataset,
    normalize_spectrum_file_name,
)
from app.spectrum_memory.mzml_spectrum_extract import extract_spectrum


class MzmlScanReaderError(RuntimeError):
    """Base error for indexed single-spectrum access."""


class RunNotFoundError(MzmlScanReaderError):
    pass


class MzmlFileNotFoundError(MzmlScanReaderError):
    pass


class MzmlMappingError(MzmlScanReaderError):
    pass


class UnsupportedMzmlError(MzmlScanReaderError):
    pass


class UnsupportedNativeIdError(UnsupportedMzmlError):
    pass


class MzmlIndexError(MzmlScanReaderError):
    pass


class SpectrumNotFoundError(MzmlScanReaderError):
    pass


_NATIVE_SCAN_RE = re.compile(r"(?:^|[\s;])(?:scan|index)=(\d+)(?=$|[\s;])")
_INDEX_LIST_OFFSET_RE = re.compile(br"<indexListOffset>\d+</indexListOffset>")
_INDEX_CACHE_LOCK = threading.RLock()
_INDEX_CACHE: dict[tuple[str, int, int], dict[int, str]] = {}


class _StrictPreIndexedMzML(mzml.PreIndexedMzML):
    """Disable Pyteomics' full-file indexing fallback."""

    def build_byte_index(self):  # type: ignore[no-untyped-def]
        index = self._find_index_list()
        try:
            spectrum_index = index["spectrum"]
        except (KeyError, TypeError):
            spectrum_index = None
        if not spectrum_index:
            raise UnsupportedMzmlError("mzML does not contain a usable embedded spectrum index")
        return index


def _resolve_run_mzml_path(
    session: Session,
    dataset_id: int,
    run_id: int,
) -> tuple[Path, bool]:
    row = session.execute(
        text(
            """
            SELECT run_id, dataset_id, file_name, run_metadata
            FROM runs
            WHERE run_id = :run_id AND dataset_id = :dataset_id
            """
        ),
        {"run_id": run_id, "dataset_id": dataset_id},
    ).mappings().one_or_none()
    if row is None:
        raise RunNotFoundError("run not found")

    run_metadata = row.get("run_metadata") or {}
    mzml_path = run_metadata.get("mzml_file_path")
    path_committed = False
    if not mzml_path:
        ds = session.execute(
            text("SELECT source_root, capabilities FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).mappings().one_or_none()
        if ds is None:
            raise RunNotFoundError("dataset not found")
        source_root = Path(str(ds.get("source_root") or "")).resolve()
        try:
            mapping = build_mapping_from_extracted_dataset(ingest_root=source_root).mapping
        except Exception as exc:  # noqa: BLE001
            raise MzmlMappingError(f"cannot derive mzML mapping: {exc}") from exc
        file_name = str(row.get("file_name") or "")
        mapped = mapping.get(normalize_spectrum_file_name(file_name))
        if mapped is None:
            raise MzmlMappingError(f"cannot map run.file_name to mzML: {file_name}")
        mzml_path = str(mapped)
        session.execute(
            text(
                "UPDATE runs SET run_metadata = run_metadata || CAST(:patch AS jsonb) "
                "WHERE run_id = :run_id"
            ),
            {"run_id": run_id, "patch": json.dumps({"mzml_file_path": mzml_path}, ensure_ascii=False)},
        )
        session.execute(
            text(
                "UPDATE datasets SET capabilities = capabilities || CAST(:cap_patch AS jsonb) "
                "WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id, "cap_patch": '{"spectra_source": "mzml_memory"}'},
        )
        session.commit()
        path_committed = True

    raw_path = Path(str(mzml_path))
    missing_before = not raw_path.is_file()
    path = try_fix_stale_incoming_absolute_path(raw_path)
    if path is None:
        raise MzmlFileNotFoundError(f"mzML not found: {mzml_path}")
    if missing_before and str(path) != str(mzml_path):
        session.execute(
            text(
                "UPDATE runs SET run_metadata = run_metadata || CAST(:patch AS jsonb) "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": run_id,
                "patch": json.dumps({"mzml_file_path": str(path)}, ensure_ascii=False),
            },
        )
        session.commit()
        path_committed = True

    return path, path_committed


def _cache_key(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise MzmlFileNotFoundError(f"cannot stat mzML file: {path}") from exc
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns


def _require_embedded_index(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            tail = handle.read()
    except OSError as exc:
        raise MzmlFileNotFoundError(f"cannot read mzML file: {path}") from exc
    if _INDEX_LIST_OFFSET_RE.search(tail) is None:
        raise UnsupportedMzmlError("mzML does not contain an embedded indexListOffset")


def _scan_number(native_id: str) -> int | None:
    match = _NATIVE_SCAN_RE.search(native_id)
    return int(match.group(1)) if match else None


def _get_cached_scan_index(key: tuple[str, int, int]) -> dict[int, str] | None:
    with _INDEX_CACHE_LOCK:
        return _INDEX_CACHE.get(key)


def _store_scan_index(
    key: tuple[str, int, int],
    scan_index: dict[int, str],
) -> None:
    with _INDEX_CACHE_LOCK:
        path = key[0]
        stale_keys = [existing for existing in _INDEX_CACHE if existing[0] == path and existing != key]
        for stale_key in stale_keys:
            _INDEX_CACHE.pop(stale_key, None)
        _INDEX_CACHE[key] = scan_index


def _build_scan_index(native_ids: Any) -> dict[int, str]:
    scan_index: dict[int, str] = {}
    for native_id in native_ids:
        scan_number = _scan_number(str(native_id))
        if scan_number is None:
            continue
        existing = scan_index.get(scan_number)
        if existing is not None and existing != native_id:
            raise MzmlIndexError(f"multiple native IDs map to scan number {scan_number}")
        scan_index[scan_number] = str(native_id)
    if not scan_index:
        raise UnsupportedNativeIdError(
            "embedded mzML index has no parseable scan or index native IDs"
        )
    return scan_index


def read_indexed_spectrum(path: Path, scan_number: int) -> dict[str, Any]:
    resolved = path.resolve()
    lower_name = resolved.name.lower()
    if lower_name.endswith((".mzml.gz", ".mzml.gzip")):
        raise UnsupportedMzmlError("gzip-compressed mzML does not support indexed random access")
    if not lower_name.endswith(".mzml"):
        raise UnsupportedMzmlError(f"not an mzML file: {resolved}")

    key = _cache_key(resolved)
    _require_embedded_index(resolved)
    scan_index = _get_cached_scan_index(key)
    try:
        with _StrictPreIndexedMzML(str(resolved)) as reader:
            if scan_index is None:
                scan_index = _build_scan_index(reader.default_index)
                _store_scan_index(key, scan_index)
            native_id = scan_index.get(scan_number)
            if native_id is None:
                raise SpectrumNotFoundError(f"scan not found in mzML: {scan_number}")
            spec = reader.get_by_id(native_id, element_type="spectrum")
    except MzmlScanReaderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MzmlIndexError(f"cannot read indexed mzML {resolved}: {exc}") from exc

    if not isinstance(spec, dict) or spec.get("id") != native_id:
        raise MzmlIndexError(f"indexed mzML returned an invalid spectrum for scan {scan_number}")
    return extract_spectrum(spec, scan_number)


def get_spectrum_by_scan(
    session: Session,
    dataset_id: int,
    run_id: int,
    scan_number: int,
) -> tuple[dict[str, Any], bool]:
    path, path_committed = _resolve_run_mzml_path(session, dataset_id, run_id)
    return read_indexed_spectrum(path, scan_number), path_committed
