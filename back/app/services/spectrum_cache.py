"""LRU cache for MS1 / MS2 spectrum files (still stored on disk).

Resolution order for a dataset's spectrum directory:

1. ``datasets.source_root`` from the row (absolute path captured at import).
2. ``DATA_ROOT / slug_dir(slug)`` as a fallback, so moving the ``shuju``
   tree to a different machine / drive letter still works without rewriting
   the database.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.js_parser import load_js_object


class SpectrumNotFoundError(FileNotFoundError):
    """Raised when the requested spectrum file is missing on disk."""


def _slug_dir_name(slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug.strip()).strip("._-")
    return safe or "dataset"


def _candidate_roots(slug: str, source_root: str | None) -> list[Path]:
    roots: list[Path] = []
    if source_root:
        p = Path(source_root)
        if not p.is_absolute():
            p = (settings.resolved_data_root / p).resolve()
        else:
            p = p.resolve()
        roots.append(p)
    fallback = (settings.resolved_data_root / _slug_dir_name(slug)).resolve()
    if fallback not in roots:
        roots.append(fallback)
    return roots


@lru_cache(maxsize=256)
def _load_spectrum(abs_path: str) -> dict[str, Any]:
    path = Path(abs_path)
    if not path.exists():
        raise SpectrumNotFoundError(str(path))
    return load_js_object(path)


def _resolve_spectrum(slug: str, source_root: str | None, sub: str, spec_id: int) -> Path:
    rel = Path("topfd") / sub / f"spectrum{spec_id}.js"
    for root in _candidate_roots(slug, source_root):
        candidate = (root / rel).resolve()
        if candidate.exists():
            return candidate
    # Return the first candidate even if missing so the error message is
    # informative (points at the canonical location).
    return (_candidate_roots(slug, source_root)[0] / rel).resolve()


def get_ms1_spectrum(slug: str, source_root: str | None, spec_id: int) -> dict[str, Any]:
    path = _resolve_spectrum(slug, source_root, "ms1_json", spec_id)
    return _load_spectrum(str(path))


def get_ms2_spectrum(slug: str, source_root: str | None, spec_id: int) -> dict[str, Any]:
    path = _resolve_spectrum(slug, source_root, "ms2_json", spec_id)
    return _load_spectrum(str(path))


def clear_cache() -> None:
    _load_spectrum.cache_clear()
