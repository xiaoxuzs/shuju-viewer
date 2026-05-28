"""Read-only filesystem probes for TopPIC admission."""

from __future__ import annotations

from pathlib import Path

from app.dataset_ingest_root.resolver import has_bu_diann_layout
from app.services.import_planner.detectors import is_toppic_html_tree
from app.services.mzml_mapping import collect_mzml_files
from app.services.prsm_files import (
    ingest_root_has_supported_prsm_files,
    iter_prsm_files,
    prsm_bundle_prsm_directory,
)

from .types import SignalSnapshot

_PRSM_XML_SUFFIX = "_toppic_prsm.xml"
_MS2_MSALIGN_SUFFIX = "_ms2.msalign"


def _glob_prsm_xml(root: Path) -> list[Path]:
    toppic = root / "toppic"
    if not toppic.is_dir():
        return []
    files = [p.resolve() for p in toppic.rglob(f"*{_PRSM_XML_SUFFIX}") if p.is_file()]
    return sorted({str(p): p for p in files}.values(), key=lambda p: str(p).lower())


def _glob_ms2_msalign(root: Path) -> list[Path]:
    topfd = root / "topfd"
    if not topfd.is_dir():
        return []
    files = [p.resolve() for p in topfd.rglob(f"*{_MS2_MSALIGN_SUFFIX}") if p.is_file()]
    return sorted({str(p): p for p in files}.values(), key=lambda p: str(p).lower())


def _count_supported_prsm_files(ingest_root: Path) -> int:
    total = 0
    for directory in (
        ingest_root / "data",
        ingest_root / "data" / "prsms",
        ingest_root / "toppic_prsm_cutoff" / "data_js" / "prsms",
        ingest_root / "toppic_proteoform_cutoff" / "data_js" / "prsms",
    ):
        total += len(iter_prsm_files(directory))
    return total


def collect_signals(ingest_root: Path) -> SignalSnapshot:
    """Collect layout facts under *ingest_root* without making admission decisions."""
    root = ingest_root.resolve()
    prsm_xml = tuple(_glob_prsm_xml(root))
    ms2_msalign = tuple(_glob_ms2_msalign(root))
    mzml = tuple(collect_mzml_files(root))
    has_prsm = ingest_root_has_supported_prsm_files(root)
    return SignalSnapshot(
        has_topfd=(root / "topfd").is_dir(),
        has_toppic_dir=(root / "toppic").is_dir(),
        prsm_xml_files=prsm_xml,
        ms2_msalign_files=ms2_msalign,
        mzml_files=mzml,
        has_supported_prsm_files=has_prsm,
        prsm_file_count=_count_supported_prsm_files(root),
        is_toppic_html_tree=is_toppic_html_tree(root),
        prsm_bundle_dir=prsm_bundle_prsm_directory(root),
        is_bu_diann_layout=has_bu_diann_layout(root),
    )
