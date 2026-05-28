"""Narrow DTOs passed into spectrum_memory (no ORM / FastAPI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MzmlRunFileSpec:
    """One run row mapped to a resolved mzML path on disk."""

    run_id: int
    mzml_path: Path


@dataclass(frozen=True)
class MzmlBundleSpec:
    """All mzML-backed runs for one dataset that must be loaded as a unit."""

    dataset_id: int
    runs: tuple[MzmlRunFileSpec, ...]
