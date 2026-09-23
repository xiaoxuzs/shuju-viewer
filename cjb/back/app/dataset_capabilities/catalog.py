"""Viewer's deliberately small, executable view catalog."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RequirementSpec:
    entity: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ViewerViewSpec:
    view_id: str
    title: str
    route: str
    requirements: tuple[RequirementSpec, ...]
    analysis_modes: tuple[str, ...] = ("BOTTOM_UP", "TOP_DOWN", "SPECTRA_ONLY")


_CANONICAL_VIEW_SPECS = (
    ViewerViewSpec(
        view_id="spectra",
        title="Spectra",
        route="/datasets/{slug}",
        requirements=(RequirementSpec("spectra"),),
    ),
    ViewerViewSpec(
        view_id="bu.matches",
        title="Bottom-Up matches",
        route="/datasets/{slug}/matches",
        requirements=(RequirementSpec("psms"),),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="bu.peptides",
        title="Bottom-Up peptides",
        route="/datasets/{slug}/peptides",
        requirements=(RequirementSpec("peptides"),),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="bu.proteins",
        title="Bottom-Up proteins",
        route="/datasets/{slug}/proteins",
        requirements=(RequirementSpec("proteins"),),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="bu.protein_coverage",
        title="Protein sequence coverage",
        route="/datasets/{slug}/proteins/{protein_id}",
        requirements=(
            RequirementSpec("proteins"),
            RequirementSpec("protein_sequences"),
            RequirementSpec("peptide_positions"),
            RequirementSpec("protein_sequence_completeness", required=False),
            RequirementSpec("peptide_position_completeness", required=False),
        ),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="chromatogram",
        title="Chromatogram",
        route="/datasets/{slug}",
        requirements=(RequirementSpec("chromatograms"),),
        analysis_modes=("BOTTOM_UP", "SPECTRA_ONLY"),
    ),
    ViewerViewSpec(
        view_id="fragment_annotation",
        title="Fragment annotation",
        route="/datasets/{slug}/matches/{match_id}",
        requirements=(
            RequirementSpec("psms"),
            RequirementSpec("spectra"),
            RequirementSpec("spectrum_links"),
            RequirementSpec("fragment_annotations"),
        ),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="quantification",
        title="Quantification",
        route="/datasets/{slug}/matches/{match_id}",
        requirements=(
            RequirementSpec("psms"),
            RequirementSpec("quantification"),
            RequirementSpec("quantification_completeness", required=False),
            RequirementSpec("quantification_semantics", required=False),
        ),
        analysis_modes=("BOTTOM_UP",),
    ),
    ViewerViewSpec(
        view_id="td.proteins",
        title="Top-Down proteins",
        route="/datasets/{slug}/{cutoff}/proteins",
        requirements=(RequirementSpec("proteins"),),
        analysis_modes=("TOP_DOWN",),
    ),
    ViewerViewSpec(
        view_id="td.proteoforms",
        title="Top-Down proteoforms",
        route="/datasets/{slug}/{cutoff}/proteoforms",
        requirements=(RequirementSpec("proteoforms"),),
        analysis_modes=("TOP_DOWN",),
    ),
    ViewerViewSpec(
        view_id="td.prsms",
        title="Top-Down PrSMs",
        route="/datasets/{slug}/{cutoff}/prsms",
        requirements=(RequirementSpec("prsms"),),
        analysis_modes=("TOP_DOWN",),
    ),
)


_LEGACY_VIEW_ALIASES = {
    "bu_matches": "bu.matches",
    "bu_peptides": "bu.peptides",
    "bu_proteins": "bu.proteins",
    "protein_coverage": "bu.protein_coverage",
}


def _catalog() -> dict[str, ViewerViewSpec]:
    result = {item.view_id: item for item in _CANONICAL_VIEW_SPECS}
    for alias, canonical in _LEGACY_VIEW_ALIASES.items():
        source = result[canonical]
        result[alias] = ViewerViewSpec(
            view_id=alias,
            title=source.title,
            route=source.route,
            requirements=source.requirements,
            analysis_modes=source.analysis_modes,
        )
    return result


VIEWER_VIEW_CATALOG: Mapping[str, ViewerViewSpec] = MappingProxyType(_catalog())


def get_view_catalog(analysis_mode: str | None = None) -> tuple[ViewerViewSpec, ...]:
    """Return the stable catalog in UI display order."""

    if analysis_mode is None:
        return _CANONICAL_VIEW_SPECS
    normalized = analysis_mode.upper()
    return tuple(item for item in _CANONICAL_VIEW_SPECS if normalized in item.analysis_modes)
