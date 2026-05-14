"""Whole-dataset mzML memory pool (MRU/LRU, global byte budget).

Public API for other packages: :func:`ensure_dataset_resident`,
:func:`get_mzml_spectrum`, :func:`release_dataset`, :func:`residency_of`.
"""

from __future__ import annotations

from typing import Any

from app.spectrum_memory.contracts import MzmlBundleSpec, MzmlRunFileSpec
from app.spectrum_memory.types import CapacityError, NotResidentError, Residency


def _get_coordinator():
    from app.spectrum_memory.eviction_coordinator import get_coordinator

    return get_coordinator()

__all__ = [
    "CapacityError",
    "MzmlBundleSpec",
    "MzmlRunFileSpec",
    "NotResidentError",
    "Residency",
    "ensure_dataset_resident",
    "get_mzml_spectrum",
    "release_dataset",
    "residency_of",
]


def ensure_dataset_resident(spec: MzmlBundleSpec) -> None:
    _get_coordinator().ensure_dataset_resident(spec)


def get_mzml_spectrum(dataset_id: int, run_id: int, scan_number: int) -> dict[str, Any] | None:
    return _get_coordinator().get_mzml_spectrum(dataset_id, run_id, scan_number)


def release_dataset(dataset_id: int) -> None:
    _get_coordinator().release_dataset(dataset_id)


def residency_of(dataset_id: int) -> Residency:
    return _get_coordinator().residency_of(dataset_id)
