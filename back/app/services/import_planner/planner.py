"""Build :class:`~app.services.import_planner.types.ImportPlan` for a ZIP ingest root."""

from __future__ import annotations

from pathlib import Path

from app.services.prsm_files import has_prsm_files, ingest_root_has_supported_prsm_files

from .detectors import detect_spectra_source, is_toppic_html_tree
from .types import DatasetShape, ImportLayoutError, ImportPlan

_NO_PRSM_TOPPIC = (
    "This TopPIC HTML output is missing PrSM detail files. "
    "Add supported prsm*.js|json|txt under data/ or under "
    "toppic_prsm_cutoff|toppic_proteoform_cutoff/data_js/prsms/, then re-import."
)

_UNSUPPORTED = (
    "Unsupported ZIP layout. Provide either a TopPIC HTML output tree "
    "(toppic_*_cutoff/data_js/proteins.js plus PrSM detail files) "
    "or supported PrSM detail files under data/."
)

_PRSM_BUNDLE_NO_MZML = (
    "PrSM detail bundle requires mzML mode (TopFD ms1/ms2 spectrum*.js not found in topfd/)."
)


def plan_zip_ingest(ingest_root: Path) -> ImportPlan:
    """Infer dataset shape, spectra source, and post-ingest steps.

    Rules:
    - TopPIC HTML imports **require** on-disk PrSM detail files
      (:func:`app.services.prsm_files.ingest_root_has_supported_prsm_files`).
    - PrSM-only bundle under ``data/`` requires ``mzml_memory`` (same as job runner).
    """
    root = ingest_root.resolve()
    toppic = is_toppic_html_tree(root)
    prsm_bundle = has_prsm_files(root / "data")

    if toppic:
        if not ingest_root_has_supported_prsm_files(root):
            raise ImportLayoutError(_NO_PRSM_TOPPIC)
        src = detect_spectra_source(root)
        return ImportPlan(
            shape=DatasetShape.TOPPIC_HTML,
            spectra_source=src,
            need_toppic_multirun_pass=(src == "mzml_memory"),
        )

    if prsm_bundle:
        src = detect_spectra_source(root)
        if src != "mzml_memory":
            raise ImportLayoutError(_PRSM_BUNDLE_NO_MZML)
        return ImportPlan(
            shape=DatasetShape.PRSM_BUNDLE,
            spectra_source=src,
            need_toppic_multirun_pass=False,
        )

    raise ImportLayoutError(_UNSUPPORTED)
