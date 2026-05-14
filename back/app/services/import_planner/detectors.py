"""Read-only layout / spectra-source detection for a dataset root on disk."""

from __future__ import annotations

from pathlib import Path

from app.services.mzml_mapping import collect_mzml_files

_TOPPIC_CUTOFF_DIRS: tuple[str, ...] = ("toppic_prsm_cutoff", "toppic_proteoform_cutoff")


def is_toppic_html_tree(ingest_root: Path) -> bool:
    """True when a TopPIC HTML ``data_js`` tree exists (either cutoff folder name)."""
    root = ingest_root.resolve()
    return any((root / cutoff_dir / "data_js" / "proteins.js").is_file() for cutoff_dir in _TOPPIC_CUTOFF_DIRS)


def detect_spectra_source(ingest_root: Path) -> str:
    """Pick ``topfd_js`` vs ``mzml_memory`` for spectrum payloads.

    If any mzML is present in the extracted tree, always prefer ``mzml_memory``.
    Many “full” TopPIC HTML ZIPs ship a partial ``topfd/*/spectrum*.js`` tree
    (or a few placeholder files) while PrSM headers still reference TopFD ids
    that do not exist on disk; PrSM-only bundles instead rely on mzML and work.
    When there is no mzML, fall back to TopFD JS if both MS1 and MS2 dirs have
    at least one ``spectrum*.js`` file.
    """
    root = ingest_root.resolve()
    if collect_mzml_files(root):
        return "mzml_memory"
    topfd_ms1_dir = root / "topfd" / "ms1_json"
    topfd_ms2_dir = root / "topfd" / "ms2_json"
    has_topfd_ms1 = topfd_ms1_dir.is_dir() and any(topfd_ms1_dir.glob("spectrum*.js"))
    has_topfd_ms2 = topfd_ms2_dir.is_dir() and any(topfd_ms2_dir.glob("spectrum*.js"))
    if has_topfd_ms1 and has_topfd_ms2:
        return "topfd_js"
    return "mzml_memory"
