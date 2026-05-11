"""Helpers for discovering and reading TopPIC PrSM detail files.目前支持.js,.json,.txt三种后缀的文件"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.services.js_parser import load_js_object

SUPPORTED_PRSM_SUFFIXES: tuple[str, ...] = (".js", ".json", ".txt")


def is_prsm_file(path: Path, *, suffixes: tuple[str, ...] = SUPPORTED_PRSM_SUFFIXES) -> bool:
    """Return whether ``path`` looks like a supported PrSM detail file."""
    return path.is_file() and path.stem.startswith("prsm") and path.suffix.lower() in suffixes


def prsm_sort_key(path: Path) -> tuple[int, str]:
    """Sort ``prsm123.ext`` files numerically while keeping a deterministic fallback."""
    try:
        return (int(path.stem.removeprefix("prsm")), path.name)
    except ValueError:
        return (1 << 30, path.name)


def iter_prsm_files(
    directory: Path,
    *,
    suffixes: tuple[str, ...] = SUPPORTED_PRSM_SUFFIXES,
    key: Callable[[Path], object] | None = None,
) -> list[Path]:
    """List supported ``prsm*`` files directly under ``directory``."""
    if not directory.exists() or not directory.is_dir():
        return []

    normalized_suffixes = tuple(suffix.lower() for suffix in suffixes)
    files = [path for path in directory.iterdir() if is_prsm_file(path, suffixes=normalized_suffixes)]
    return sorted(files, key=key or (lambda path: path.name))


def has_prsm_files(directory: Path, *, suffixes: tuple[str, ...] = SUPPORTED_PRSM_SUFFIXES) -> bool:
    """Return whether ``directory`` contains at least one supported PrSM file."""
    return bool(iter_prsm_files(directory, suffixes=suffixes))


def ingest_root_has_supported_prsm_files(ingest_root: Path) -> bool:
    """True when the extracted archive contains supported PrSM detail filenames.

    ZIP import requires this for TopPIC HTML trees so PrSM headers can be read
    for mzML run assignment and detail APIs.
    """
    if has_prsm_files(ingest_root / "data"):
        return True
    for cutoff_dir in ("toppic_prsm_cutoff", "toppic_proteoform_cutoff"):
        if has_prsm_files(ingest_root / cutoff_dir / "data_js" / "prsms"):
            return True
    return False


def prsm_detail_path(directory: Path, prsm_id: int) -> Path | None:
    """Resolve ``prsm{id}`` using the supported suffix order."""
    stem = f"prsm{prsm_id}"
    candidates = {path.suffix.lower(): path for path in iter_prsm_files(directory) if path.stem == stem}
    for suffix in SUPPORTED_PRSM_SUFFIXES:
        candidate = candidates.get(suffix)
        if candidate is not None:
            return candidate
    return None


def prsm_paths_by_id(directory: Path) -> dict[int, Path]:
    """Map ``prsm`` numeric id → file path with one directory scan.

    Suffix preference matches :func:`prsm_detail_path`. Use this for bulk work
    (e.g. fast import) instead of calling :func:`prsm_detail_path` per row, which
    would re-list the directory on every call.
    """
    by_id: dict[int, dict[str, Path]] = {}
    for path in iter_prsm_files(directory):
        stem = path.stem
        if not stem.startswith("prsm"):
            continue
        try:
            pid = int(stem.removeprefix("prsm"))
        except ValueError:
            continue
        by_id.setdefault(pid, {})[path.suffix.lower()] = path
    out: dict[int, Path] = {}
    for prsm_id, candidates in by_id.items():
        for suffix in SUPPORTED_PRSM_SUFFIXES:
            chosen = candidates.get(suffix)
            if chosen is not None:
                out[prsm_id] = chosen
                break
    return out


def load_prsm_document(path: Path) -> dict[str, Any]:
    """Read a supported PrSM detail file and return its JSON-like document."""
    return load_js_object(path)


def get_prsm_root(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize supported TopPIC PrSM document wrappers to the PrSM object."""
    prsm = doc.get("prsm")
    if isinstance(prsm, dict):
        return prsm

    prsm_data = doc.get("prsm_data")
    if isinstance(prsm_data, dict):
        nested_prsm = prsm_data.get("prsm")
        if isinstance(nested_prsm, dict):
            return nested_prsm

    return doc


def extract_spectrum_file_name(path: Path) -> str:
    """Read ``ms.ms_header.spectrum_file_name`` from a PrSM detail file."""
    doc = load_prsm_document(path)
    prsm_root = get_prsm_root(doc)
    ms = prsm_root.get("ms", {}) or {}
    header = ms.get("ms_header", {}) or {}
    raw_name = header.get("spectrum_file_name")
    if raw_name is None:
        raise ValueError(f"missing ms_header.spectrum_file_name in {path}")
    raw_text = str(raw_name).strip()
    if raw_text == "":
        raise ValueError(f"empty ms_header.spectrum_file_name in {path}")
    return raw_text
