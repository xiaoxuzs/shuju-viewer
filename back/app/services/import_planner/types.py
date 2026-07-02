"""Types for import planning (layout, spectra source, downstream steps)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DatasetShape(str, Enum):
    """Recognized dataset layout under an ingest root."""

    TOPPIC_HTML = "toppic_html"
    PRSM_BUNDLE = "prsm_bundle"
    DIANN_DIA = "diann_dia"
    UNSUPPORTED = "unsupported"


class ImportLayoutError(ValueError):
    """Raised when the archive layout or required files do not meet import rules."""


@dataclass(frozen=True)
class ImportPlan:
    """Immutable plan produced before DB ingest or heavy I/O."""

    shape: DatasetShape
    """``TOPPIC_HTML``, ``PRSM_BUNDLE``, or ``DIANN_DIA``."""

    spectra_source: str
    """Spectra source string used in ``datasets.capabilities``."""

    need_toppic_multirun_pass: bool
    """When True, run :func:`assign_toppic_runs_from_prsm_headers` after fast TopPIC ingest."""

    contains_raw: bool = False
    """True when Thermo ``.raw`` files were detected under the ingest root."""

    raw_files: tuple[Path, ...] = ()
    """Detected Thermo ``.raw`` files. Planner only records them; conversion happens later."""

    raw_vendor: str | None = None
    """P0 vendor label for detected RAW files."""

    requires_raw_conversion: bool = False
    """True when the import job should run the RAW conversion phase."""
