"""Capability projection for a deeply validated declarative semantic dataset."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.declarative_ingest.semantic_schema import SemanticDataset

from .compiler import compile_capability_report
from .contracts import (
    CapabilityAmbiguity,
    CapabilityWarning,
    DatasetCapabilityReport,
    EntityCapability,
    FactState,
    MissingInput,
    ValidatedDatasetFacts,
)


_USABLE_SEMANTIC_STATES = frozenset({"DIRECT", "DERIVED"})
_PEPTIDE_POSITION_DERIVATION = "viewer.peptide-position.exact-subsequence.v1"
_CHROMATOGRAM_DERIVATION = "viewer.chromatogram.tic-bpc.v1"


def compile_semantic_capability_report(
    dataset_id: int,
    source_case_id: str | None,
    semantic: SemanticDataset,
    requested_view_ids: Iterable[str] | None = None,
) -> DatasetCapabilityReport:
    """Compile only capabilities evidenced by a validated semantic payload."""

    spectrum_facts = _spectrum_facts(semantic)
    sequence_facts = _protein_sequence_facts(semantic)
    position_facts = _peptide_position_facts(semantic)
    quantification_facts = _quantification_facts(semantic)
    entities = [
        spectrum_facts[0],
        _collection_fact("psms", semantic.identifications, "semantic.identifications"),
        _collection_fact("peptides", semantic.peptides, "semantic.peptides"),
        _collection_fact(
            "proteins",
            semantic.proteins,
            "semantic.proteins",
            present_reason="PROTEIN_ACCESSIONS_PRESENT",
        ),
        _collection_fact("protein_groups", semantic.protein_groups, "semantic.protein_groups"),
        sequence_facts[0],
        sequence_facts[1],
        position_facts[0],
        position_facts[1],
        spectrum_facts[1],
        _chromatogram_fact(semantic, spectrum_facts[0]),
        EntityCapability(
            entity="fragment_annotations",
            state=FactState.MISSING,
            count=0,
            reason_code="SEMANTIC_FRAGMENT_ANNOTATIONS_ABSENT",
            evidence_refs=["semantic.fragment_annotations:absent"],
        ),
        _collection_fact("modifications", semantic.modifications, "semantic.modifications"),
        _decoy_fact(semantic),
        quantification_facts[0],
        quantification_facts[1],
        quantification_facts[2],
        _collection_fact("runs", semantic.runs, "semantic.runs"),
        _collection_fact("relationships", semantic.relationships, "semantic.relationships"),
    ]
    missing_inputs = _missing_inputs(semantic)
    ambiguities = _ambiguities(semantic, position_facts[0], quantification_facts[2])
    facts = ValidatedDatasetFacts(
        dataset_id=dataset_id,
        source_case_id=source_case_id,
        analysis_mode="BOTTOM_UP",
        entities=entities,
        missing_inputs=missing_inputs,
        ambiguities=ambiguities,
        warnings=_warnings(semantic),
    )
    return compile_capability_report(facts, requested_view_ids=requested_view_ids)


def _collection_fact(
    entity: str,
    records: list[Any],
    evidence_path: str,
    *,
    present_reason: str = "SEMANTIC_ENTITY_PRESENT",
) -> EntityCapability:
    return EntityCapability(
        entity=entity,
        state=FactState.DIRECT if records else FactState.MISSING,
        count=len(records),
        reason_code=present_reason if records else "SEMANTIC_ENTITY_EMPTY",
        evidence_refs=_evidence(records, evidence_path),
    )


def _spectrum_facts(semantic: SemanticDataset) -> tuple[EntityCapability, EntityCapability]:
    identifications = semantic.identifications
    linked = [
        item
        for item in identifications
        if item.spectrum_id and item.spectrum_link_state in _USABLE_SEMANTIC_STATES
    ]
    spectrum_ids = {str(item.spectrum_id) for item in linked}
    state_counts = Counter(item.spectrum_link_state for item in identifications)
    evidence = _evidence(identifications, "semantic.identifications[].spectrum_link_state")
    core_spectrum_count = int(getattr(semantic, "core_spectrum_count", 0))
    observed_spectrum_count = core_spectrum_count or len(spectrum_ids)
    if observed_spectrum_count:
        spectra = EntityCapability(
            entity="spectra",
            state=FactState.DIRECT,
            count=observed_spectrum_count,
            reason_code="CORE_SPECTRA_PRESENT" if core_spectrum_count else "LINKED_CORE_SPECTRA_PRESENT",
            evidence_refs=(
                [*evidence, "semantic.core_spectrum_count"]
                if core_spectrum_count
                else evidence
            ),
        )
    else:
        state = _unavailable_state(state_counts)
        spectra = EntityCapability(
            entity="spectra",
            state=state,
            count=0,
            reason_code="NO_VERIFIED_SPECTRA" if state is FactState.MISSING else "SPECTRUM_LINKS_UNRESOLVED",
            evidence_refs=evidence,
        )

    linked_count = len(linked)
    if state_counts["DIRECT"]:
        link_state = FactState.DIRECT
        derivation_id = None
    elif state_counts["DERIVED"]:
        link_state = FactState.DERIVED
        derivation_id = f"declarative-plan:{semantic.plan_sha256}:spectrum-links"
    else:
        link_state = _unavailable_state(state_counts)
        derivation_id = None
    spectrum_links = EntityCapability(
        entity="spectrum_links",
        state=link_state,
        count=linked_count,
        reason_code=(
            "SPECTRUM_LINKS_COMPLETE"
            if identifications and linked_count == len(identifications)
            else "SPECTRUM_LINKS_PARTIAL"
            if linked_count
            else "SPECTRUM_LINKS_UNAVAILABLE"
        ),
        evidence_refs=evidence,
        derivation_id=derivation_id,
    )
    return spectra, spectrum_links


def _protein_sequence_facts(semantic: SemanticDataset) -> tuple[EntityCapability, EntityCapability]:
    proteins = semantic.proteins
    state_counts = Counter(item.sequence_state for item in proteins)
    usable = [item for item in proteins if item.sequence and item.sequence_state in _USABLE_SEMANTIC_STATES]
    evidence = _evidence(proteins, "semantic.proteins[].sequence_state")
    if state_counts["DIRECT"]:
        state = FactState.DIRECT
        derivation_id = None
    elif state_counts["DERIVED"]:
        state = FactState.DERIVED
        derivation_id = f"declarative-plan:{semantic.plan_sha256}:protein-sequences"
    else:
        state = _unavailable_state(state_counts)
        derivation_id = None
    sequences = EntityCapability(
        entity="protein_sequences",
        state=state,
        count=len(usable),
        reason_code=(
            "PROTEIN_SEQUENCES_COMPLETE"
            if proteins and len(usable) == len(proteins)
            else "PROTEIN_SEQUENCES_PARTIAL"
            if usable
            else "PROTEIN_SEQUENCES_UNAVAILABLE"
        ),
        evidence_refs=evidence,
        derivation_id=derivation_id,
    )
    completeness_state = (
        FactState.DIRECT
        if proteins and len(usable) == len(proteins)
        else _unavailable_state(state_counts)
    )
    completeness = EntityCapability(
        entity="protein_sequence_completeness",
        state=completeness_state,
        count=len(usable),
        reason_code=(
            "ALL_PROTEIN_SEQUENCES_AVAILABLE"
            if completeness_state is FactState.DIRECT
            else "PROTEIN_SEQUENCE_COVERAGE_INCOMPLETE"
        ),
        evidence_refs=evidence,
    )
    return sequences, completeness


def _peptide_position_facts(semantic: SemanticDataset) -> tuple[EntityCapability, EntityCapability]:
    peptides = {item.peptide_id: item for item in semantic.peptides}
    resolved = 0
    missing = 0
    ambiguous = 0
    total = 0
    coverage_ready_proteins = 0
    relevant: list[Any] = []
    for protein in semantic.proteins:
        relevant.append(protein)
        protein_unresolved = False
        for peptide_id in protein.peptide_ids:
            total += 1
            peptide = peptides.get(peptide_id)
            if peptide is None or not protein.sequence:
                missing += 1
                protein_unresolved = True
                continue
            relevant.append(peptide)
            first = protein.sequence.find(peptide.sequence)
            if first < 0:
                missing += 1
                protein_unresolved = True
            elif protein.sequence.find(peptide.sequence, first + 1) >= 0:
                ambiguous += 1
                protein_unresolved = True
            else:
                resolved += 1
        if protein.sequence and not protein_unresolved:
            coverage_ready_proteins += 1
    evidence = _evidence(relevant, "semantic.proteins[].peptide_ids")
    derivation_id = _PEPTIDE_POSITION_DERIVATION if resolved or coverage_ready_proteins else None
    if resolved or coverage_ready_proteins:
        state = FactState.DERIVED
    elif ambiguous:
        state = FactState.AMBIGUOUS
    else:
        state = FactState.MISSING
    positions = EntityCapability(
        entity="peptide_positions",
        state=state,
        count=resolved,
        reason_code=(
            "PEPTIDE_POSITIONS_COMPLETE"
            if resolved == total
            else "PEPTIDE_POSITIONS_PARTIAL"
            if resolved
            else "PEPTIDE_POSITIONS_AMBIGUOUS"
            if ambiguous
            else "PEPTIDE_POSITIONS_UNAVAILABLE"
        ),
        evidence_refs=evidence,
        derivation_id=derivation_id,
    )
    if resolved == total and (total > 0 or any(item.sequence for item in semantic.proteins)):
        completeness_state = FactState.DERIVED
        completeness_derivation = _PEPTIDE_POSITION_DERIVATION
    elif ambiguous:
        completeness_state = FactState.AMBIGUOUS
        completeness_derivation = None
    else:
        completeness_state = FactState.MISSING
        completeness_derivation = None
    completeness = EntityCapability(
        entity="peptide_position_completeness",
        state=completeness_state,
        count=resolved,
        reason_code=(
            "ALL_PEPTIDE_POSITIONS_RESOLVED"
            if completeness_state is FactState.DERIVED
            else "PEPTIDE_POSITION_COVERAGE_INCOMPLETE"
        ),
        evidence_refs=evidence,
        derivation_id=completeness_derivation,
    )
    return positions, completeness


def _quantification_facts(
    semantic: SemanticDataset,
) -> tuple[EntityCapability, EntityCapability, EntityCapability]:
    records = semantic.quantification
    valued = [item for item in records if item.value is not None]
    with_unit = [item for item in valued if item.unit]
    evidence = _evidence(records, "semantic.quantification")
    quantification = EntityCapability(
        entity="quantification",
        state=FactState.DIRECT if valued else FactState.MISSING,
        count=len(records),
        reason_code=(
            "QUANTIFICATION_COMPLETE"
            if records and len(valued) == len(records)
            else "QUANTIFICATION_PARTIAL"
            if valued
            else "QUANTIFICATION_UNAVAILABLE"
        ),
        evidence_refs=evidence,
    )
    completeness = EntityCapability(
        entity="quantification_completeness",
        state=FactState.DIRECT if records and len(valued) == len(records) else FactState.MISSING,
        count=len(valued),
        reason_code=(
            "ALL_QUANTIFICATION_VALUES_AVAILABLE"
            if records and len(valued) == len(records)
            else "QUANTIFICATION_VALUES_INCOMPLETE"
        ),
        evidence_refs=evidence,
    )
    semantics = EntityCapability(
        entity="quantification_semantics",
        state=(
            FactState.DIRECT
            if valued and len(with_unit) == len(valued)
            else FactState.AMBIGUOUS
            if valued
            else FactState.MISSING
        ),
        count=len(with_unit),
        reason_code=(
            "QUANTIFICATION_UNITS_DECLARED"
            if valued and len(with_unit) == len(valued)
            else "QUANTIFICATION_UNITS_AMBIGUOUS"
            if valued
            else "QUANTIFICATION_SEMANTICS_UNAVAILABLE"
        ),
        evidence_refs=evidence,
    )
    return quantification, completeness, semantics


def _decoy_fact(semantic: SemanticDataset) -> EntityCapability:
    known = sum(item.is_decoy is not None for item in semantic.proteins)
    if semantic.proteins and known == len(semantic.proteins):
        state = FactState.DIRECT
        reason = "DECOY_LABELS_COMPLETE"
    elif known:
        state = FactState.AMBIGUOUS
        reason = "DECOY_LABELS_PARTIAL"
    else:
        state = FactState.MISSING
        reason = "DECOY_LABELS_UNAVAILABLE"
    return EntityCapability(
        entity="decoy_labels",
        state=state,
        count=known,
        reason_code=reason,
        evidence_refs=_evidence(semantic.proteins, "semantic.proteins[].is_decoy"),
    )


def _chromatogram_fact(semantic: SemanticDataset, spectra: EntityCapability) -> EntityCapability:
    core_chromatogram_count = int(getattr(semantic, "core_chromatogram_count", 0))
    if core_chromatogram_count:
        return EntityCapability(
            entity="chromatograms",
            state=FactState.DIRECT,
            count=core_chromatogram_count,
            reason_code="CORE_CHROMATOGRAMS_PRESENT",
            evidence_refs=["semantic.core_chromatogram_count"],
        )
    if spectra.state in {FactState.DIRECT, FactState.DERIVED}:
        linked_run_ids = {
            item.run_id
            for item in semantic.identifications
            if item.spectrum_id and item.spectrum_link_state in _USABLE_SEMANTIC_STATES
        }
        return EntityCapability(
            entity="chromatograms",
            state=FactState.DERIVED,
            count=len(linked_run_ids),
            reason_code="DERIVABLE_FROM_VERIFIED_SPECTRA",
            evidence_refs=spectra.evidence_refs,
            derivation_id=_CHROMATOGRAM_DERIVATION,
        )
    return EntityCapability(
        entity="chromatograms",
        state=FactState.MISSING,
        count=0,
        reason_code="SPECTRA_REQUIRED_FOR_CHROMATOGRAM",
        evidence_refs=spectra.evidence_refs,
    )


def _missing_inputs(semantic: SemanticDataset) -> list[MissingInput]:
    result: list[MissingInput] = []
    missing_sequences = sum(item.sequence_state == "MISSING" for item in semantic.proteins)
    if semantic.proteins and missing_sequences:
        has_fasta = any(item.reader == "fasta" for item in semantic.source_files)
        result.append(
            MissingInput(
                input_id="fasta",
                label="Search FASTA",
                reason_code="FASTA_INCOMPLETE" if has_fasta else "FASTA_MISSING",
                message=(
                    f"{missing_sequences} protein accessions lack a reference sequence; "
                    "provide the exact FASTA used for this search."
                ),
                unlocks=["bu.protein_coverage"],
            )
        )
    if semantic.identifications and int(getattr(semantic, "core_spectrum_count", 0)) == 0:
        result.append(
            MissingInput(
                input_id="spectrum_source",
                label="Spectrum source",
                reason_code="SPECTRUM_SOURCE_MISSING",
                message="No validated mzML or supported spectrum source was supplied for these identifications.",
                unlocks=["spectra", "chromatogram", "fragment_annotation"],
            )
        )
    if semantic.identifications and not getattr(semantic, "fragment_annotations", []):
        result.append(
            MissingInput(
                input_id="fragment_annotations",
                label="Source fragment annotations",
                reason_code="FRAGMENT_ANNOTATIONS_MISSING",
                message=(
                    "No source fragment-ion annotations were supplied; Viewer will not claim source b/y matches."
                ),
                unlocks=["fragment_annotation"],
            )
        )
    return result


def _ambiguities(
    semantic: SemanticDataset,
    positions: EntityCapability,
    quantification_semantics: EntityCapability,
) -> list[CapabilityAmbiguity]:
    result: list[CapabilityAmbiguity] = []
    ambiguous_spectra = sum(item.spectrum_link_state == "AMBIGUOUS" for item in semantic.identifications)
    if ambiguous_spectra:
        result.append(
            CapabilityAmbiguity(
                ambiguity_id="spectrum_links",
                message=f"{ambiguous_spectra} identifications have an ambiguous spectrum link.",
                evidence_refs=_evidence(
                    semantic.identifications,
                    "semantic.identifications[].spectrum_link_state",
                ),
                affected_views=["fragment_annotation"],
            )
        )
    ambiguous_sequences = sum(item.sequence_state == "AMBIGUOUS" for item in semantic.proteins)
    if ambiguous_sequences:
        result.append(
            CapabilityAmbiguity(
                ambiguity_id="protein_sequences",
                message=f"{ambiguous_sequences} protein accessions match multiple reference sequences.",
                evidence_refs=_evidence(semantic.proteins, "semantic.proteins[].sequence_state"),
                affected_views=["bu.protein_coverage"],
            )
        )
    if positions.state is FactState.AMBIGUOUS:
        result.append(
            CapabilityAmbiguity(
                ambiguity_id="peptide_positions",
                message="Peptide positions are not unique within the available protein sequences.",
                evidence_refs=positions.evidence_refs,
                affected_views=["bu.protein_coverage"],
            )
        )
    if quantification_semantics.state is FactState.AMBIGUOUS:
        result.append(
            CapabilityAmbiguity(
                ambiguity_id="quantification_semantics",
                message="One or more quantitative values have no declared unit.",
                evidence_refs=quantification_semantics.evidence_refs,
                affected_views=["quantification"],
            )
        )
    return result


def _warnings(semantic: SemanticDataset) -> list[CapabilityWarning]:
    used_ids: set[str] = set()
    result: list[CapabilityWarning] = []
    if any(item.is_decoy is None for item in semantic.proteins):
        used_ids.add("decoy_labels_unavailable")
        result.append(
            CapabilityWarning(
                warning_id="decoy_labels_unavailable",
                message=(
                    "DECOY_LABELS_UNAVAILABLE: one or more proteins have no target/decoy evidence; "
                    "Viewer must not interpret the storage default as a scientific target label."
                ),
                evidence_refs=["semantic.proteins[].is_decoy"],
            )
        )
    for index, message in enumerate(semantic.warnings):
        prefix = message.partition(":")[0]
        base = re.sub(r"[^a-z0-9]+", "_", prefix.casefold()).strip("_") or "semantic_warning"
        warning_id = base
        suffix = 2
        while warning_id in used_ids:
            warning_id = f"{base}_{suffix}"
            suffix += 1
        used_ids.add(warning_id)
        result.append(
            CapabilityWarning(
                warning_id=warning_id,
                message=message,
                evidence_refs=[f"semantic.warnings[{index}]"],
            )
        )
    for index, asset in enumerate(getattr(semantic, "asset_dispositions", [])):
        label = asset.disposition.casefold()
        warning_id = f"{label}_asset_{index + 1}"
        suffix = 2
        while warning_id in used_ids:
            warning_id = f"{label}_asset_{index + 1}_{suffix}"
            suffix += 1
        used_ids.add(warning_id)
        prefix = {
            "UNSUPPORTED": "VIEWER_UNSUPPORTED",
            "PROVENANCE_ONLY": "PROVENANCE_ONLY",
            "IRRELEVANT": "EXPLICITLY_IRRELEVANT",
        }[asset.disposition]
        result.append(
            CapabilityWarning(
                warning_id=warning_id,
                message=f"{prefix}: {asset.relative_path}: {asset.reason}",
                evidence_refs=list(asset.evidence_refs),
            )
        )
    return result


def _unavailable_state(state_counts: Counter[str]) -> FactState:
    if state_counts["AMBIGUOUS"]:
        return FactState.AMBIGUOUS
    if state_counts["VIEWER_UNSUPPORTED"] and not state_counts["MISSING"]:
        return FactState.VIEWER_UNSUPPORTED
    return FactState.MISSING


def _evidence(records: Iterable[Any], fallback: str) -> list[str]:
    refs = {fallback}
    for record in records:
        refs.update(str(item) for item in getattr(record, "evidence_refs", []) if item)
    return sorted(refs)
