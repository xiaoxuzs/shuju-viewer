"""Validate a user-selected import type against an already planned physical layout."""

from __future__ import annotations

from pathlib import Path

from app.import_types import ImportType
from app.ingest.bu.diaclip_source import inspect_diaclip_source
from app.services.import_planner.types import DatasetShape, ImportPlan


class ImportSelectionError(ValueError):
    """Raised when the selected import type does not match the supplied dataset."""


def validate_import_selection(
    import_type: ImportType,
    ingest_root: Path,
    plan: ImportPlan,
) -> None:
    """Reject content that does not satisfy the explicitly selected import type."""
    raw_types = {ImportType.TD_RAW, ImportType.DDA_RAW, ImportType.RAW_ONLY}
    mzml_types = {ImportType.TD_MZML, ImportType.MZML_ONLY}
    toppic_html_types = {ImportType.TD_TOPPIC_HTML, ImportType.TOPPIC}
    prsm_bundle_types = {ImportType.TD_PRSM_BUNDLE, ImportType.PRSM}
    dia_nn_types = {ImportType.BU_DIA_NN, ImportType.DIA_NN}
    dia_clip_types = {ImportType.BU_DIA_CLIP, ImportType.DIA_CLIP}
    if import_type in dia_clip_types:
        if plan.shape != DatasetShape.DIANN_DIA:
            raise ImportSelectionError(
                f"The selected import type {import_type.value} does not match the dataset layout. "
                "Choose the matching import type or provide the files described by the upload form."
            )
        inspect_diaclip_source(ingest_root)
        return

    matches = (
        (import_type in raw_types and plan.shape == DatasetShape.MZML_ONLY and plan.contains_raw)
        or (import_type in mzml_types and plan.shape == DatasetShape.MZML_ONLY and not plan.contains_raw)
        or (import_type in toppic_html_types and plan.shape == DatasetShape.TOPPIC_HTML)
        or (import_type in prsm_bundle_types and plan.shape == DatasetShape.PRSM_BUNDLE)
        or (import_type == ImportType.TD_TOPPIC_NATIVE and plan.shape == DatasetShape.TOPPIC_NATIVE)
        or (import_type in dia_nn_types and plan.shape == DatasetShape.DIANN_DIA)
    )
    if not matches:
        raise ImportSelectionError(
            f"The selected import type {import_type.value} does not match the dataset layout. "
            "Choose the matching import type or provide the files described by the upload form."
        )

def default_import_kind(plan: ImportPlan) -> str:
    """Stable duplicate-key kind for legacy path imports without an explicit type."""
    if plan.shape == DatasetShape.MZML_ONLY:
        return ImportType.RAW_ONLY.value if plan.contains_raw else ImportType.MZML_ONLY.value
    return {
        DatasetShape.TOPPIC_HTML: ImportType.TD_TOPPIC_HTML.value,
        DatasetShape.PRSM_BUNDLE: ImportType.TD_PRSM_BUNDLE.value,
        DatasetShape.TOPPIC_NATIVE: ImportType.TD_TOPPIC_NATIVE.value,
        DatasetShape.DIANN_DIA: ImportType.BU_DIA_NN.value,
    }.get(plan.shape, plan.shape.value.upper())
