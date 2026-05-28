"""Validate PFMB adaptation staging output."""

from __future__ import annotations

from pathlib import Path

from app.services.prsm_files import has_prsm_files
from app.services.mzml_mapping import collect_mzml_files


class AdaptValidationError(ValueError):
    """Staging layout is incomplete after PFMB adaptation."""


def validate_adapted_staging(staging_root: Path) -> None:
    """Ensure staging root is ready for ``PRSM_BUNDLE`` import."""
    root = staging_root.resolve()
    prsms_dir = root / "data" / "prsms"
    if not prsms_dir.is_dir():
        raise AdaptValidationError(f"missing data/prsms directory under staging root: {root}")
    if not has_prsm_files(prsms_dir, suffixes=(".json",)):
        raise AdaptValidationError(f"no prsm*.json files under {prsms_dir}")
    if not collect_mzml_files(root):
        raise AdaptValidationError(f"no mzML files under staging root: {root}")
