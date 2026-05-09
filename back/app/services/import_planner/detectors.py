"""Read-only layout / spectra-source detection for extracted ZIP roots."""

from __future__ import annotations

from pathlib import Path

_TOPPIC_CUTOFF_DIRS: tuple[str, ...] = ("toppic_prsm_cutoff", "toppic_proteoform_cutoff")


def is_toppic_html_tree(ingest_root: Path) -> bool:
    """True when a TopPIC HTML ``data_js`` tree exists (either cutoff folder name)."""
    root = ingest_root.resolve()
    return any((root / cutoff_dir / "data_js" / "proteins.js").is_file() for cutoff_dir in _TOPPIC_CUTOFF_DIRS)


def detect_spectra_source(ingest_root: Path) -> str:
    """Return ``topfd_js`` when TopFD spectrum JS exists for MS1 and MS2; else ``mzml_memory``."""
    root = ingest_root.resolve()
    topfd_ms1_dir = root / "topfd" / "ms1_json"
    topfd_ms2_dir = root / "topfd" / "ms2_json"
    has_topfd_ms1 = topfd_ms1_dir.is_dir() and any(topfd_ms1_dir.glob("spectrum*.js"))
    has_topfd_ms2 = topfd_ms2_dir.is_dir() and any(topfd_ms2_dir.glob("spectrum*.js"))
    if has_topfd_ms1 and has_topfd_ms2:
        return "topfd_js"
    return "mzml_memory"
