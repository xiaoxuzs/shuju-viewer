"""LRU cache for MS1 / MS2 spectrum files (still stored on disk)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.js_parser import load_js_object


class SpectrumNotFoundError(FileNotFoundError):
    """Raised when the requested spectrum file is missing on disk."""


def _dataset_root(dataset_slug: str, dataset_source_path: str | None = None) -> Path:
    """Resolve a dataset directory from its slug.

    ``dataset_source_path`` from the DB row wins if provided; otherwise we
    fall back to ``DATA_ROOT / slug``.
    """
    if dataset_source_path:
        p = Path(dataset_source_path)
        if not p.is_absolute():
            p = (settings.resolved_data_root / p).resolve()
        return p
    return settings.resolved_data_root / dataset_slug


@lru_cache(maxsize=256)
def _load_spectrum(abs_path: str) -> dict[str, Any]:
    path = Path(abs_path)
    if not path.exists():
        raise SpectrumNotFoundError(str(path))
    return load_js_object(path)


def get_ms1_spectrum(dataset_source_path: str, spec_id: int) -> dict[str, Any]:
    path = Path(dataset_source_path) / "topfd" / "ms1_json" / f"spectrum{spec_id}.js"
    return _load_spectrum(str(path.resolve()))


def get_ms2_spectrum(dataset_source_path: str, spec_id: int) -> dict[str, Any]:
    path = Path(dataset_source_path) / "topfd" / "ms2_json" / f"spectrum{spec_id}.js"
    return _load_spectrum(str(path.resolve()))


def clear_cache() -> None:
    _load_spectrum.cache_clear()
