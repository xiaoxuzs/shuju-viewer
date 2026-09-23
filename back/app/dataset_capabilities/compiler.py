"""Pure compilation from verified dataset facts to Viewer capabilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .catalog import VIEWER_VIEW_CATALOG, get_view_catalog
from .contracts import (
    CapabilityAmbiguity,
    CapabilityWarning,
    DatasetCapabilityReport,
    EntityCapability,
    FactState,
    ValidatedDatasetFacts,
    ViewAvailability,
    ViewCapability,
    ViewRequirement,
)


_USABLE_STATES = frozenset({FactState.DIRECT, FactState.DERIVED})
_LEGACY_ENTITY_ORDER = (
    "spectra",
    "psms",
    "peptides",
    "proteins",
    "protein_sequences",
    "peptide_positions",
    "chromatograms",
    "fragment_annotations",
    "quantification",
    "modifications",
    "proteoforms",
    "prsms",
)


def compile_capability_report(
    facts: ValidatedDatasetFacts,
    *,
    requested_view_ids: Iterable[str] | None = None,
) -> DatasetCapabilityReport:
    """Compile a report without filesystem, database, or network access."""

    entity_by_id = {item.entity: item for item in facts.entities}
    view_ids = (
        tuple(requested_view_ids)
        if requested_view_ids is not None
        else tuple(spec.view_id for spec in get_view_catalog(facts.analysis_mode))
    )
    entities = list(facts.entities)
    referenced_entities = {
        requirement.entity
        for view_id in view_ids
        if (spec := VIEWER_VIEW_CATALOG.get(view_id)) is not None
        for requirement in spec.requirements
    }
    for entity in sorted(referenced_entities - entity_by_id.keys()):
        fact = EntityCapability(
            entity=entity,
            state=FactState.AMBIGUOUS,
            count=None,
            reason_code="FACT_NOT_VALIDATED",
            evidence_refs=[],
        )
        entity_by_id[entity] = fact
        entities.append(fact)

    views = [
        _compile_view(view_id, entity_by_id)
        for view_id in view_ids
    ]
    return DatasetCapabilityReport(
        dataset_id=facts.dataset_id,
        source_case_id=facts.source_case_id,
        entities=entities,
        views=views,
        missing_inputs=facts.missing_inputs,
        ambiguities=facts.ambiguities,
        warnings=facts.warnings,
    )


def compile_legacy_capability_report(
    *,
    dataset_id: int,
    capabilities: Mapping[str, Any] | None,
    source_case_id: str | None = None,
    analysis_mode: str | None = None,
) -> DatasetCapabilityReport:
    """Conservatively translate only explicit legacy capability signals."""

    caps = dict(capabilities or {})
    facts = [_legacy_entity_fact(entity, caps) for entity in _LEGACY_ENTITY_ORDER]
    ambiguous_entities = {item.entity for item in facts if item.state is FactState.AMBIGUOUS}
    affected_views = [
        spec.view_id
        for spec in get_view_catalog()
        if any(requirement.entity in ambiguous_entities for requirement in spec.requirements)
    ]
    ambiguities = (
        [
            CapabilityAmbiguity(
                ambiguity_id="legacy_capabilities_incomplete",
                message=(
                    "Legacy metadata does not declare every fact needed by the Viewer; "
                    "undeclared facts remain ambiguous."
                ),
                evidence_refs=["datasets.capabilities"],
                affected_views=affected_views,
            )
        ]
        if ambiguous_entities
        else []
    )
    validated = ValidatedDatasetFacts(
        dataset_id=dataset_id,
        source_case_id=source_case_id,
        analysis_mode=(
            analysis_mode.upper()
            if analysis_mode and analysis_mode.upper() in {"BOTTOM_UP", "TOP_DOWN", "SPECTRA_ONLY"}
            else None
        ),
        entities=facts,
        ambiguities=ambiguities,
        warnings=[
            CapabilityWarning(
                warning_id="legacy_capability_metadata",
                message=(
                    "This report was conservatively inferred from legacy dataset capabilities; "
                    "run Agent validation to produce a complete evidence-backed report."
                ),
                evidence_refs=["datasets.capabilities"],
            )
        ],
    )
    report = compile_capability_report(validated)
    return report.model_copy(
        update={"provenance": "LEGACY_METADATA", "enforcement": "ADVISORY"}
    )


def validate_capability_report(
    payload: object,
    *,
    expected_dataset_id: int | None = None,
    expected_analysis_mode: str | None = None,
) -> DatasetCapabilityReport:
    """Validate a persisted report and its executable view states."""

    report = DatasetCapabilityReport.model_validate(payload)
    if expected_dataset_id is not None and report.dataset_id != expected_dataset_id:
        raise ValueError("capability report dataset_id does not match the requested dataset")
    for view in report.views:
        spec = VIEWER_VIEW_CATALOG.get(view.view_id)
        if spec is None:
            if view.availability is not ViewAvailability.DISABLED or not any(
                item.state is FactState.VIEWER_UNSUPPORTED for item in view.requirements
            ):
                raise ValueError(f"unregistered view must be VIEWER_UNSUPPORTED and DISABLED: {view.view_id}")
            continue
        if expected_analysis_mode and expected_analysis_mode.upper() not in spec.analysis_modes:
            raise ValueError(
                f"view {view.view_id} is incompatible with analysis mode {expected_analysis_mode}"
            )
        if view.title != spec.title or view.route != spec.route:
            raise ValueError(f"registered view metadata does not match catalog: {view.view_id}")
        entity_by_id = {item.entity: item for item in report.entities}
        missing_entities = [item.entity for item in spec.requirements if item.entity not in entity_by_id]
        if missing_entities:
            raise ValueError(
                f"registered view references absent entity facts: {view.view_id}: {', '.join(missing_entities)}"
            )
        expected = _compile_view(view.view_id, entity_by_id)
        if view != expected:
            raise ValueError(f"registered view state does not match its facts: {view.view_id}")
    return report


def _compile_view(view_id: str, entity_by_id: Mapping[str, EntityCapability]) -> ViewCapability:
    spec = VIEWER_VIEW_CATALOG.get(view_id)
    if spec is None:
        return ViewCapability(
            view_id=view_id,
            title=view_id,
            route="",
            availability=ViewAvailability.DISABLED,
            requirements=[
                ViewRequirement(
                    entity=f"viewer_view:{view_id}",
                    state=FactState.VIEWER_UNSUPPORTED,
                    required=True,
                    reason_code="VIEW_NOT_REGISTERED",
                )
            ],
            reason_code="VIEWER_UNSUPPORTED",
            message="Viewer does not register this view.",
        )

    requirements = [_requirement(item.entity, item.required, entity_by_id) for item in spec.requirements]
    unavailable_required = [
        item for item in requirements if item.required and item.state not in _USABLE_STATES
    ]
    unavailable_optional = [
        item for item in requirements if not item.required and item.state not in _USABLE_STATES
    ]
    if unavailable_required:
        return ViewCapability(
            view_id=spec.view_id,
            title=spec.title,
            route=spec.route,
            availability=ViewAvailability.DISABLED,
            requirements=requirements,
            reason_code=_view_reason(unavailable_required, disabled=True),
            message=_view_message("unavailable", unavailable_required),
        )
    if unavailable_optional:
        return ViewCapability(
            view_id=spec.view_id,
            title=spec.title,
            route=spec.route,
            availability=ViewAvailability.PARTIAL,
            requirements=requirements,
            reason_code=_view_reason(unavailable_optional, disabled=False),
            message=_view_message("partially available", unavailable_optional),
        )
    return ViewCapability(
        view_id=spec.view_id,
        title=spec.title,
        route=spec.route,
        availability=ViewAvailability.AVAILABLE,
        requirements=requirements,
        reason_code=None,
        message="All declared requirements are available.",
    )


def _requirement(
    entity: str,
    required: bool,
    entity_by_id: Mapping[str, EntityCapability],
) -> ViewRequirement:
    fact = entity_by_id[entity]
    return ViewRequirement(
        entity=entity,
        state=fact.state,
        required=required,
        reason_code=fact.reason_code,
        derivation_id=fact.derivation_id,
    )


def _view_reason(requirements: list[ViewRequirement], *, disabled: bool) -> str:
    states = {item.state for item in requirements}
    if FactState.VIEWER_UNSUPPORTED in states:
        return "VIEWER_UNSUPPORTED"
    if FactState.AMBIGUOUS in states:
        return "REQUIREMENT_AMBIGUOUS" if disabled else "OPTIONAL_REQUIREMENT_AMBIGUOUS"
    return "REQUIRED_DATA_MISSING" if disabled else "OPTIONAL_DATA_MISSING"


def _view_message(kind: str, requirements: list[ViewRequirement]) -> str:
    names = ", ".join(item.entity for item in requirements)
    return f"This view is {kind}: {names}."


def _legacy_entity_fact(entity: str, caps: Mapping[str, Any]) -> EntityCapability:
    true_refs, false_refs = _legacy_signals(entity, caps)
    if true_refs:
        return EntityCapability(
            entity=entity,
            state=FactState.DIRECT,
            count=None,
            reason_code="LEGACY_CAPABILITY_DECLARED",
            evidence_refs=true_refs,
        )
    if false_refs:
        return EntityCapability(
            entity=entity,
            state=FactState.MISSING,
            count=None,
            reason_code="LEGACY_CAPABILITY_FALSE",
            evidence_refs=false_refs,
        )
    return EntityCapability(
        entity=entity,
        state=FactState.AMBIGUOUS,
        count=None,
        reason_code="LEGACY_CAPABILITY_NOT_DECLARED",
        evidence_refs=[],
    )


def _legacy_signals(entity: str, caps: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    boolean_keys = {
        "spectra": ("has_spectrum_files", "has_ms1", "has_ms2"),
        "psms": ("has_identifications",),
        "peptides": ("has_peptides",),
        "proteins": ("has_proteins",),
        "protein_sequences": ("has_protein_sequences",),
        "peptide_positions": ("has_peptide_positions",),
        "chromatograms": ("has_chromatogram",),
        "fragment_annotations": ("has_fragment_annotations", "has_ms2_pfmb"),
        "quantification": ("has_quantification",),
        "modifications": ("has_modifications",),
        "proteoforms": ("has_proteoforms",),
        "prsms": ("has_prsms",),
    }[entity]
    true_refs = [f"capabilities.{key}" for key in boolean_keys if caps.get(key) is True]
    false_refs = [f"capabilities.{key}" for key in boolean_keys if caps.get(key) is False]

    binary_layer = caps.get("binary_layer")
    if entity == "spectra" and isinstance(binary_layer, Mapping) and binary_layer.get("spectra") is True:
        true_refs.append("capabilities.binary_layer.spectra")

    list_routes = caps.get("list_routes")
    routes = {str(item) for item in list_routes} if isinstance(list_routes, list) else set()
    route_for_entity = {"psms": "matches", "peptides": "peptides", "proteins": "proteins"}.get(entity)
    if route_for_entity in routes:
        true_refs.append(f"capabilities.list_routes:{route_for_entity}")

    entity_types = caps.get("entity_types")
    types = {str(item).upper() for item in entity_types} if isinstance(entity_types, list) else set()
    if entity == "peptides" and "PEPTIDE" in types:
        true_refs.append("capabilities.entity_types:PEPTIDE")
    return true_refs, false_refs
