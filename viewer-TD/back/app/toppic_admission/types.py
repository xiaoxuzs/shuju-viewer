"""Pure data types for TopPIC dataset admission (file discrimination)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AdmissionRoute(str, Enum):
    DIRECT_INGEST = "direct_ingest"
    NEED_PFMB = "need_pfmb"
    UNSUPPORTED = "unsupported"


class DirectIngestShape(str, Enum):
    TOPPIC_HTML = "toppic_html"
    PRSM_BUNDLE = "prsm_bundle"


class PfmbIngestSource(str, Enum):
    XML_MSALIGN = "xml_msalign"
    TOPPIC_JS = "toppic_js"


@dataclass(frozen=True)
class RunTriple:
    """One TopPIC pipeline run: PFMB ingest inputs."""

    prsm_xml: Path
    ms2_msalign: Path
    mzml: Path
    run_key: str


@dataclass(frozen=True)
class SignalSnapshot:
    """Read-only filesystem facts collected under an ingest root."""

    has_topfd: bool
    has_toppic_dir: bool
    prsm_xml_files: tuple[Path, ...]
    ms2_msalign_files: tuple[Path, ...]
    mzml_files: tuple[Path, ...]
    has_supported_prsm_files: bool
    prsm_file_count: int
    is_toppic_html_tree: bool
    prsm_bundle_dir: Path | None
    is_bu_diann_layout: bool


@dataclass(frozen=True)
class AdmissionEvidence:
    """Human-readable evidence attached to an admission decision."""

    has_topfd: bool
    has_toppic_dir: bool
    has_prsm_xml: bool
    has_ms2_msalign: bool
    has_mzml: bool
    prsm_file_count: int
    is_toppic_html_tree: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdmissionDecision:
    route: AdmissionRoute
    ingest_root: Path
    evidence: AdmissionEvidence
    direct_shape: DirectIngestShape | None = None
    pfmb_source: PfmbIngestSource | None = None
    run_triples: tuple[RunTriple, ...] = field(default_factory=tuple)
    reject_reason: str | None = None
    reject_code: str | None = None

    @property
    def is_supported(self) -> bool:
        return self.route != AdmissionRoute.UNSUPPORTED
