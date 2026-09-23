"""Read-only layout / spectra-source detection for a dataset root on disk."""

from __future__ import annotations

from pathlib import Path

from app.raw_conversion.discovery import collect_raw_files
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
    if collect_mzml_files(root) or collect_raw_files(root):
        return "mzml_memory"
    topfd_ms1_dir = root / "topfd" / "ms1_json"
    topfd_ms2_dir = root / "topfd" / "ms2_json"
    has_topfd_ms1 = topfd_ms1_dir.is_dir() and any(topfd_ms1_dir.glob("spectrum*.js"))
    has_topfd_ms2 = topfd_ms2_dir.is_dir() and any(topfd_ms2_dir.glob("spectrum*.js"))
    if has_topfd_ms1 and has_topfd_ms2:
        return "topfd_js"
    return "mzml_memory"


def detect_bu_spectra_source(ingest_root: Path) -> str:
    """Pick DIA-NN Bottom-Up spectrum source: mzML memory, Bruker TDF, or mixed."""
    root = ingest_root.resolve()
    has_mzml = bool(collect_mzml_files(root))
    has_raw = bool(collect_raw_files(root))
    has_tdf = any(p.is_dir() for p in root.rglob("*.d"))
    has_mzml_like = has_mzml or has_raw
    if has_mzml_like and has_tdf:
        return "mixed"
    if has_mzml_like:
        return "mzml_memory"
    if has_tdf:
        return "tdf_memory"
    return "mzml_memory"


def has_mzml_or_raw_spectra(ingest_root: Path) -> bool:
    """True when a root contains standalone mzML files or Thermo RAW files."""
    root = ingest_root.resolve()
    has_mzml = any(path.name.lower().endswith(".mzml") for path in collect_mzml_files(root))
    return has_mzml or bool(collect_raw_files(root))
