"""Build :class:`~app.services.import_planner.types.ImportPlan` for a resolved on-disk ingest root."""

from __future__ import annotations

from pathlib import Path

from app.dataset_ingest_root.resolver import has_bu_diann_layout
from app.raw_conversion.contracts import RAW_VENDOR_THERMO
from app.raw_conversion.discovery import collect_raw_files
from app.services.mzml_mapping import collect_mzml_files
from app.services.prsm_files import ingest_root_has_supported_prsm_files, prsm_bundle_prsm_directory

from .detectors import detect_bu_spectra_source, detect_spectra_source, has_mzml_or_raw_spectra, is_toppic_html_tree
from .types import DatasetShape, ImportLayoutError, ImportPlan

_NO_PRSM_TOPPIC = (
    "This TopPIC HTML layout is missing PrSM detail files. "
    "Add supported prsm*.js|json|txt under data/, data/prsms/, or under "
    "toppic_prsm_cutoff|toppic_proteoform_cutoff/data_js/prsms/, then run the import again."
)

_UNSUPPORTED = (
    "Unsupported dataset folder layout at the resolved ingest root (path import). "
    "Expected either (1) TopPIC HTML output: toppic_prsm_cutoff or toppic_proteoform_cutoff "
    "with data_js/proteins.js plus PrSM detail files (prsm*.js|json|txt in data/, data/prsms/, or under "
    "that cutoff's data_js/prsms/), or (2) a PrSM-only bundle: supported prsm* under data/ or data/prsms/ "
    "with mzML present in the tree so spectra use mzml_memory mode, or (3) standalone mzML-only/Thermo RAW-only "
    "spectra files for basic spectra viewing."
)

_PRSM_BUNDLE_NO_MZML = (
    "PrSM files under data/ or data/prsms/ require mzML-backed spectra here. Add *.mzML under the dataset tree, "
    "or remove topfd/ms1_json and topfd/ms2_json spectrum*.js files that force TopFD JS mode."
)


def _collect_uncompressed_mzml_files(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in collect_mzml_files(root) if path.name.lower().endswith(".mzml"))


def plan_zip_ingest(ingest_root: Path) -> ImportPlan:
    """Infer dataset shape, spectra source, and post-ingest steps for a folder on disk.

    Used for path-based imports after :func:`~app.dataset_ingest_root.resolve_ingest_root`.

    Rules:
    - TopPIC HTML imports **require** on-disk PrSM detail files
      (:func:`app.services.prsm_files.ingest_root_has_supported_prsm_files`).
    - PrSM-only bundle under ``data/`` or ``data/prsms/`` requires ``mzml_memory`` (same as job runner).
    """
    root = ingest_root.resolve()
    raw_files = tuple(collect_raw_files(root))
    mzml_files = _collect_uncompressed_mzml_files(root)
    raw_kwargs = {
        "contains_raw": bool(raw_files),
        "raw_files": raw_files,
        "mzml_files": mzml_files,
        "raw_vendor": RAW_VENDOR_THERMO if raw_files else None,
        "requires_raw_conversion": bool(raw_files),
    }
    toppic = is_toppic_html_tree(root)
    bu_diann = has_bu_diann_layout(root)
    prsm_bundle = prsm_bundle_prsm_directory(root) is not None

    if bu_diann:
        return ImportPlan(
            shape=DatasetShape.DIANN_DIA,
            spectra_source=detect_bu_spectra_source(root),
            need_toppic_multirun_pass=False,
            **raw_kwargs,
        )

    if toppic:
        if not ingest_root_has_supported_prsm_files(root):
            raise ImportLayoutError(_NO_PRSM_TOPPIC)
        src = detect_spectra_source(root)
        return ImportPlan(
            shape=DatasetShape.TOPPIC_HTML,
            spectra_source=src,
            need_toppic_multirun_pass=(src == "mzml_memory"),
            **raw_kwargs,
        )

    if prsm_bundle:
        src = detect_spectra_source(root)
        if src != "mzml_memory":
            raise ImportLayoutError(_PRSM_BUNDLE_NO_MZML)
        return ImportPlan(
            shape=DatasetShape.PRSM_BUNDLE,
            spectra_source=src,
            need_toppic_multirun_pass=False,
            **raw_kwargs,
        )

    if has_mzml_or_raw_spectra(root):
        return ImportPlan(
            shape=DatasetShape.MZML_ONLY,
            spectra_source="mzml_memory",
            need_toppic_multirun_pass=False,
            **raw_kwargs,
        )

    raise ImportLayoutError(_UNSUPPORTED)
