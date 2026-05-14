"""Types for import planning (layout, spectra source, downstream steps)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DatasetShape(str, Enum):
    """Recognized dataset layout under an ingest root."""

    TOPPIC_HTML = "toppic_html"
    PRSM_BUNDLE = "prsm_bundle"
    UNSUPPORTED = "unsupported"


class ImportLayoutError(ValueError):
    """Raised when the archive layout or required files do not meet import rules."""


@dataclass(frozen=True)
class ImportPlan:
    """Immutable plan produced before DB ingest or heavy I/O."""

    shape: DatasetShape
    """``TOPPIC_HTML`` or ``PRSM_BUNDLE``."""

    spectra_source: str
    """``topfd_js`` or ``mzml_memory`` (same strings as ``datasets.capabilities``)."""

    need_toppic_multirun_pass: bool
    """When True, run :func:`assign_toppic_runs_from_prsm_headers` after fast TopPIC ingest."""
