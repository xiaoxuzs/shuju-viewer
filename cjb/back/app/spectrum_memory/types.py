"""Residency and error types for the spectrum memory pool."""

from __future__ import annotations

from enum import Enum


class Residency(str, Enum):
    ABSENT = "absent"
    LOADING = "loading"
    READY = "ready"


class SpectrumMemoryError(RuntimeError):
    """Base class for spectrum_memory failures."""


class NotResidentError(SpectrumMemoryError):
    """Dataset bundle is not loaded; call ensure_dataset_resident first."""


class CapacityError(SpectrumMemoryError):
    """Cannot fit a dataset under the global byte budget even after eviction."""
