"""Locate the PFMB sidecar files for a dataset.

Two entry points:

* :func:`detect_sidecar` — used at import time with an explicit directory
  (``--pfmb-sidecar-dir``); validates that both files exist and returns the
  dict stored in ``datasets.extra_metadata.ms2_annotation``.
* :func:`resolve_sidecar` — used at request time; reads that stored dict back
  and validates the files still exist.

No drive letters are hardcoded: the directory is always supplied by the caller
(import flag) or read from the dataset's stored metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PfmbSidecar:
    pfmb_path: Path
    index_path: Path


def detect_sidecar(sidecar_dir: Path | str) -> dict[str, str] | None:
    """Return ``{"pfmb_path", "index_path"}`` if both files exist under *sidecar_dir*."""

    directory = Path(sidecar_dir)
    pfmb = directory / "results.pfmb"
    index = directory / "index.json"
    if pfmb.is_file() and index.is_file():
        return {"pfmb_path": str(pfmb.resolve()), "index_path": str(index.resolve())}
    return None


def resolve_sidecar(extra_metadata: dict[str, Any] | None) -> PfmbSidecar | None:
    """Read ``extra_metadata.ms2_annotation`` back into existing file paths."""

    annotation = (extra_metadata or {}).get("ms2_annotation")
    if not annotation:
        return None
    pfmb = Path(annotation.get("pfmb_path", ""))
    index = Path(annotation.get("index_path", ""))
    if pfmb.is_file() and index.is_file():
        return PfmbSidecar(pfmb_path=pfmb, index_path=index)
    return None
