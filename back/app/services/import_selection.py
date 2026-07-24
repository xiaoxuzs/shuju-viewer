"""Validate a user-selected import type against an already planned physical layout."""

from __future__ import annotations

from pathlib import Path

from app.import_types import ImportType
from app.ingest.bu.diaclip_result_reader import inspect_diaclip_bundle
from app.services.import_planner.types import DatasetShape, ImportPlan


class ImportSelectionError(ValueError):
    """Raised when the selected import type does not match the supplied dataset."""


def validate_import_selection(
    import_type: ImportType,
    ingest_root: Path,
    plan: ImportPlan,
) -> None:
    """Reject content that does not satisfy the explicitly selected import type."""
    matches = {
        ImportType.RAW_ONLY: plan.shape == DatasetShape.MZML_ONLY and plan.contains_raw,
        ImportType.MZML_ONLY: plan.shape == DatasetShape.MZML_ONLY and not plan.contains_raw,
        ImportType.TOPPIC: plan.shape == DatasetShape.TOPPIC_HTML,
        ImportType.PRSM: plan.shape == DatasetShape.PRSM_BUNDLE,
        ImportType.DIA_NN: plan.shape == DatasetShape.DIANN_DIA,
        ImportType.DIA_CLIP: plan.shape == DatasetShape.DIANN_DIA,
    }
    if not matches[import_type]:
        raise ImportSelectionError(
            f"The selected import type {import_type.value} does not match the dataset layout. "
            "Choose the matching import type or provide the files described by the upload form."
        )
    if import_type == ImportType.DIA_CLIP:
        inspect_diaclip_bundle(ingest_root)


def default_import_kind(plan: ImportPlan) -> str:
    """Stable duplicate-key kind for legacy path imports without an explicit type."""
    if plan.shape == DatasetShape.MZML_ONLY:
        return ImportType.RAW_ONLY.value if plan.contains_raw else ImportType.MZML_ONLY.value
    return {
        DatasetShape.TOPPIC_HTML: ImportType.TOPPIC.value,
        DatasetShape.PRSM_BUNDLE: ImportType.PRSM.value,
        DatasetShape.DIANN_DIA: ImportType.DIA_NN.value,
    }.get(plan.shape, plan.shape.value.upper())
