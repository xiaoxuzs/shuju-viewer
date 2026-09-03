from __future__ import annotations

import csv
import hashlib
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .bottom_up_schema import (
    BottomUpDocument,
    BottomUpIdentification,
    BottomUpModification,
    BottomUpPeptide,
    BottomUpProtein,
    BottomUpProteinGroup,
    BottomUpQuantification,
)
from .composite_bottom_up_bundle import (
    ADAPTER_FLAVOR,
    IDENTIFICATION_KIND,
    SOURCE_TYPE,
    CompositeBottomUpBundle,
)
from .composite_bottom_up_exceptions import CompositeBottomUpConversionError

_OXIDATION_TOKEN = "(Oxidation (M))"


@dataclass(frozen=True, slots=True)
class CompositeBottomUpAdapterReport:
    document: BottomUpDocument
    evidence_row_count: int
    protein_group_row_count: int


@dataclass(frozen=True, slots=True)
class ExactSpectrumReference:
    spectrum_id: str
    native_id: str
    rt_seconds: float


@dataclass(slots=True)
class _PeptideState:
    sequence: str
    identification_ids: set[str] = field(default_factory=set)
    modified_sequences: set[str] = field(default_factory=set)
    charges: set[int] = field(default_factory=set)
    protein_ids: set[str] = field(default_factory=set)
    group_ids: set[str] = field(default_factory=set)
    modification_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _ProteinState:
    accession: str
    is_decoy: bool = False
    name: str | None = None
    description: str | None = None
    sequence: str | None = None
    q_value: float | None = None
    peptide_ids: set[str] = field(default_factory=set)
    identification_ids: set[str] = field(default_factory=set)
    group_ids: set[str] = field(default_factory=set)
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _GroupState:
    source_group: str
    member_protein_ids: tuple[str, ...]
    leading_protein_id: str | None
    q_value: float | None
    source_fields: dict[str, Any]
    identification_ids: set[str] = field(default_factory=set)
    peptide_ids: set[str] = field(default_factory=set)
    quantification_ids: set[str] = field(default_factory=set)


class CompositeBottomUpAdapter:
    def read(
        self,
        bundle: CompositeBottomUpBundle,
        *,
        run_id: str,
        spectrum_by_scan: Mapping[int, ExactSpectrumReference],
        source_file_hashes: dict[str, str],
        raw_source_sha1: str,
    ) -> CompositeBottomUpAdapterReport:
        evidence_rows = _read_tsv(bundle.evidence)
        group_rows = _read_tsv(bundle.protein_groups)
        if len(evidence_rows) != bundle.evidence_row_count or len(group_rows) != bundle.protein_group_row_count:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SOURCE_CHANGED",
                "Result table row counts changed after inspection",
            )
        fasta = _read_fasta(bundle.fasta) if bundle.fasta else {}
        quantification: list[BottomUpQuantification] = []
        proteins: dict[str, _ProteinState] = {}
        groups = self._read_groups(
            group_rows,
            run_id=run_id,
            run_name=bundle.report_run_name,
            fasta=fasta,
            proteins=proteins,
            quantification=quantification,
        )
        peptides: dict[str, _PeptideState] = {}
        identifications: list[BottomUpIdentification] = []
        modifications: list[BottomUpModification] = []
        seen_source_ids: set[str] = set()
        seen_scans: set[int] = set()

        for row in sorted(evidence_rows, key=lambda item: _sortable_id(item.get("id"))):
            source_id = _required_text(row, "id")
            if source_id in seen_source_ids:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_EVIDENCE_ID_CONFLICT",
                    f"Duplicate evidence id: {source_id}",
                )
            seen_source_ids.add(source_id)
            sequence = _required_text(row, "Sequence")
            modified_sequence = _required_text(row, "Modified sequence")
            charge = _positive_integer(row.get("Charge"), "Charge")
            precursor_mz = _required_nonnegative(row.get("m/z"), "m/z")
            neutral_mass = _required_nonnegative(row.get("Mass"), "Mass")
            rt_seconds = _required_nonnegative(row.get("Retention time"), "Retention time") * 60.0
            scan = _positive_integer(row.get("MS/MS scan number"), "MS/MS scan number")
            spectrum = spectrum_by_scan.get(scan)
            if spectrum is None:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_EVIDENCE_SPECTRUM_MISSING",
                    f"Evidence {source_id} scan {scan} has no mzML Spectrum",
                )
            seen_scans.add(scan)
            identification_id = _stable_id("identification", source_id)
            peptide_id = _stable_id("peptide", sequence)
            group_sources = _split(row.get("Protein group IDs"))
            group_ids = tuple(_stable_id("protein_group", item) for item in group_sources)
            for source_group, group_id in zip(group_sources, group_ids):
                if group_id not in groups:
                    raise CompositeBottomUpConversionError(
                        "COMPOSITE_GROUP_REFERENCE_MISSING",
                        f"Evidence {source_id} references missing protein group {source_group}",
                    )
            accessions = _split(row.get("Proteins"))
            protein_ids = tuple(_stable_id("protein", item) for item in accessions)
            for accession, protein_id in zip(accessions, protein_ids):
                sequence_value = fasta.get(accession)
                if sequence_value is None and not _external_sequence_allowed(accession):
                    raise CompositeBottomUpConversionError(
                        "COMPOSITE_FASTA_ACCESSION_MISSING",
                        f"Target protein accession is absent from the bundled FASTA: {accession}",
                    )
                proteins.setdefault(
                    protein_id,
                    _ProteinState(
                        accession=accession,
                        is_decoy=accession.startswith("REV__"),
                        sequence=sequence_value,
                    ),
                )
            modification_ids = _modifications(
                row,
                identification_id=identification_id,
                peptide_id=peptide_id,
                sequence=sequence,
                modified_sequence=modified_sequence,
                protein_site_fields=_group_modification_site_fields(groups, group_ids),
                output=modifications,
            )
            measurements = _measurements(row, ("Intensity",), include_null=True)
            quantification_id = _stable_id("quantification", "identification", identification_id)
            quantification.append(
                BottomUpQuantification(
                    quantification_id=quantification_id,
                    entity_kind="identification",
                    entity_id=identification_id,
                    run_id=run_id,
                    sample_id=_optional_text(row.get("Experiment")) or bundle.report_run_name,
                    measurements=measurements,
                    unit="source_intensity",
                    normalization_kind=None,
                    quality={},
                )
            )
            quantification_ids = (quantification_id,)
            identification = BottomUpIdentification(
                identification_id=identification_id,
                identification_kind=IDENTIFICATION_KIND,
                run_id=run_id,
                source_run_name=bundle.report_run_name,
                source_precursor_id=source_id,
                spectrum_id=spectrum.spectrum_id,
                association_kind="exact_scan_number",
                association_rt_delta_seconds=abs(rt_seconds - spectrum.rt_seconds),
                association_precursor_mz=precursor_mz,
                peptide_id=peptide_id,
                protein_group_id=group_ids[0] if group_ids else None,
                protein_ids=protein_ids,
                modified_sequence=modified_sequence,
                stripped_sequence=sequence,
                charge=charge,
                precursor_mz=precursor_mz,
                neutral_mass=neutral_mass,
                rt_seconds=rt_seconds,
                rt_start_seconds=_rt_seconds(row, "Calibrated retention time start", rt_seconds),
                rt_stop_seconds=_rt_seconds(row, "Calibrated retention time finish", rt_seconds),
                typed_fields={
                    "score": _optional_finite(row.get("Score")),
                    "delta_score": _optional_finite(row.get("Delta score")),
                    "pep": _optional_finite(row.get("PEP")),
                    "mass_error_ppm": _optional_finite(row.get("Mass error [ppm]")),
                    "mass_error_da": _optional_finite(row.get("Mass error [Da]")),
                    "evidence_type": _optional_text(row.get("Type")),
                    "is_decoy": row.get("Decoy") == "+",
                    "is_contaminant": row.get("Potential contaminant") == "+",
                    "source_evidence_id": source_id,
                    "source_msms_ids": _split(row.get("MS/MS IDs")),
                    "source_best_msms": _optional_text(row.get("Best MS/MS")),
                },
                modification_ids=modification_ids,
                quantification_ids=quantification_ids,
                source_fields=dict(row),
                source_scan=scan,
                source_native_id=spectrum.native_id,
                rank=1,
            )
            identifications.append(identification)
            self._add_relations(identification, group_ids, peptides, proteins, groups)

        _validate_group_evidence_relations(group_rows, evidence_rows, seen_source_ids)
        peptide_records = self._peptide_records(peptides)
        protein_records = self._protein_records(proteins)
        group_records = self._group_records(groups)
        identifications.sort(key=lambda item: item.identification_id)
        modifications.sort(key=lambda item: item.modification_id)
        quantification.sort(key=lambda item: item.quantification_id)
        summary_rows = _read_tsv(bundle.summary) if bundle.summary else []
        search_parameters = _mqpar_parameters(bundle.mqpar)
        if re.fullmatch(r"[0-9a-f]{40}", raw_source_sha1) is None:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_RAW_MZML_IDENTITY_INVALID",
                "The verified RAW SHA-1 must be a lowercase 40-character digest",
            )
        metadata = {
            "source_type": SOURCE_TYPE,
            "adapter_flavor": ADAPTER_FLAVOR,
            "identification_kind": IDENTIFICATION_KIND,
            "analysis_mode": "bottom_up_dda",
            "source_software": "MaxQuant",
            "report_run_name": bundle.report_run_name,
            "core_run_id": run_id,
            "selection_policy": {"row_policy": "preserve_all_rows"},
            "field_coverage": {
                "source_column_count": len(bundle.evidence_columns) + len(bundle.protein_group_columns),
                "preserved_source_column_count": len(bundle.evidence_columns) + len(bundle.protein_group_columns),
                "evidence_columns": list(bundle.evidence_columns),
                "protein_group_columns": list(bundle.protein_group_columns),
                "preserved_in_source_fields": True,
                "unexplained_column_count": 0,
            },
            "entity_counts": {
                "identification": len(identifications),
                "peptide": len(peptide_records),
                "protein": len(protein_records),
                "protein_group": len(group_records),
                "modification": len(modifications),
                "fragment_match": 0,
                "quantification": len(quantification),
            },
            "association": {
                "identification_count": len(identifications),
                "associated_identification_count": len(identifications),
                "distinct_ms2_count": len(seen_scans),
                "dangling_spectrum_reference_count": 0,
            },
            "source_row_counts": {
                "evidence": len(evidence_rows),
                "protein_groups": len(group_rows),
                "summary": len(summary_rows),
            },
            "source_files": _source_manifest(bundle, source_file_hashes),
            "raw_mzml_identity": {
                "algorithm": "SHA-1",
                "declared_by_mzml": raw_source_sha1,
                "computed_from_raw": raw_source_sha1,
                "match": True,
            },
            "search_parameters": search_parameters,
            "modification_vocabulary": {
                "fixed": list(search_parameters.get("fixed_modifications", [])),
                "variable": list(search_parameters.get("variable_modifications", [])),
                "observed_instances": sorted({item.name for item in modifications}),
                "policy": "search-space terms are metadata; only observed localized instances become modification records",
            },
            "summary_rows": summary_rows,
            "fragment_support": {
                "status": "not_available",
                "reason": "msms.txt is absent; b/y fragment annotations cannot be fabricated",
            },
            "extension_status": {
                "bottom_up_identifications": "available",
                "bottom_up_peptides": "available",
                "bottom_up_proteins": "available",
                "bottom_up_protein_groups": "available",
                "bottom_up_modifications": "available" if modifications else "not_present",
                "bottom_up_fragment_matches": "not_available",
                "bottom_up_quantification": "available" if quantification else "not_present",
            },
        }
        document = BottomUpDocument(
            metadata=metadata,
            identifications=tuple(identifications),
            peptides=tuple(peptide_records),
            proteins=tuple(protein_records),
            protein_groups=tuple(group_records),
            modifications=tuple(modifications),
            quantification=tuple(quantification),
            warnings=(
                "msms.txt and peptides.txt are absent; source IDs are preserved without invented target records.",
                "CON__ contaminant sequences may be absent from the dataset FASTA.",
            ),
            extension_status=metadata["extension_status"],
        )
        return CompositeBottomUpAdapterReport(document, len(evidence_rows), len(group_rows))

    @staticmethod
    def _read_groups(
        rows: list[dict[str, str]],
        *,
        run_id: str,
        run_name: str,
        fasta: dict[str, str],
        proteins: dict[str, _ProteinState],
        quantification: list[BottomUpQuantification],
    ) -> dict[str, _GroupState]:
        groups: dict[str, _GroupState] = {}
        for row in sorted(rows, key=lambda item: _sortable_id(item.get("id"))):
            source_group = _required_text(row, "id")
            group_id = _stable_id("protein_group", source_group)
            if group_id in groups:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_PROTEIN_GROUP_ID_CONFLICT",
                    f"Duplicate protein group id: {source_group}",
                )
            accessions = _split(row.get("Protein IDs"))
            protein_ids = tuple(_stable_id("protein", item) for item in accessions)
            majority = _split(row.get("Majority protein IDs"))
            leading_id = _stable_id("protein", majority[0]) if majority else None
            q_value = _optional_finite(row.get("Q-value"))
            headers = _split(row.get("Fasta headers"))
            for position, (accession, protein_id) in enumerate(zip(accessions, protein_ids)):
                description = headers[position] if len(headers) == len(accessions) else None
                sequence_value = fasta.get(accession)
                if sequence_value is None and not _external_sequence_allowed(accession):
                    raise CompositeBottomUpConversionError(
                        "COMPOSITE_FASTA_ACCESSION_MISSING",
                        f"Target protein accession is absent from the bundled FASTA: {accession}",
                    )
                state = proteins.setdefault(
                    protein_id,
                    _ProteinState(
                        accession=accession,
                        is_decoy=accession.startswith("REV__"),
                        name=_protein_name(accession),
                        description=description,
                        sequence=sequence_value,
                    ),
                )
                state.q_value = _minimum(state.q_value, q_value)
                state.group_ids.add(group_id)
                state.source_fields = state.source_fields or {
                    "Protein IDs": row.get("Protein IDs"),
                    "Fasta headers": row.get("Fasta headers"),
                    "Potential contaminant": row.get("Potential contaminant"),
                }
            group = _GroupState(
                source_group=source_group,
                member_protein_ids=protein_ids,
                leading_protein_id=leading_id,
                q_value=q_value,
                source_fields=dict(row),
            )
            measurements = _measurements(row, ("Intensity", f"Intensity {run_name}"))
            if measurements:
                quantification_id = _stable_id("quantification", "protein_group", group_id)
                quantification.append(
                    BottomUpQuantification(
                        quantification_id=quantification_id,
                        entity_kind="protein_group",
                        entity_id=group_id,
                        run_id=run_id,
                        sample_id=run_name,
                        measurements=measurements,
                        unit="source_intensity",
                        normalization_kind=None,
                        quality={},
                    )
                )
                group.quantification_ids.add(quantification_id)
            groups[group_id] = group
        return groups

    @staticmethod
    def _add_relations(
        identification: BottomUpIdentification,
        group_ids: tuple[str, ...],
        peptides: dict[str, _PeptideState],
        proteins: dict[str, _ProteinState],
        groups: dict[str, _GroupState],
    ) -> None:
        peptide = peptides.setdefault(identification.peptide_id, _PeptideState(identification.stripped_sequence))
        peptide.identification_ids.add(identification.identification_id)
        peptide.modified_sequences.add(identification.modified_sequence)
        peptide.charges.add(identification.charge)
        peptide.protein_ids.update(identification.protein_ids)
        peptide.group_ids.update(group_ids)
        peptide.modification_ids.update(identification.modification_ids)
        for protein_id in identification.protein_ids:
            protein = proteins[protein_id]
            protein.peptide_ids.add(identification.peptide_id)
            protein.identification_ids.add(identification.identification_id)
            protein.group_ids.update(group_ids)
        for group_id in group_ids:
            group = groups[group_id]
            group.identification_ids.add(identification.identification_id)
            group.peptide_ids.add(identification.peptide_id)

    @staticmethod
    def _peptide_records(states: dict[str, _PeptideState]) -> list[BottomUpPeptide]:
        return [
            BottomUpPeptide(
                peptide_id=identifier,
                sequence=state.sequence,
                length=len(state.sequence),
                identification_ids=tuple(sorted(state.identification_ids)),
                modified_sequences=tuple(sorted(state.modified_sequences)),
                precursor_charges=tuple(sorted(state.charges)),
                protein_ids=tuple(sorted(state.protein_ids)),
                protein_group_ids=tuple(sorted(state.group_ids)),
                modification_ids=tuple(sorted(state.modification_ids)),
            )
            for identifier, state in sorted(states.items())
        ]

    @staticmethod
    def _protein_records(states: dict[str, _ProteinState]) -> list[BottomUpProtein]:
        return [
            BottomUpProtein(
                protein_id=identifier,
                accession=state.accession,
                is_decoy=state.is_decoy,
                name=state.name,
                gene=None,
                description=state.description,
                sequence=state.sequence,
                q_value=state.q_value,
                peptide_ids=tuple(sorted(state.peptide_ids)),
                identification_ids=tuple(sorted(state.identification_ids)),
                protein_group_ids=tuple(sorted(state.group_ids)),
                source_fields=state.source_fields,
            )
            for identifier, state in sorted(states.items())
        ]

    @staticmethod
    def _group_records(states: dict[str, _GroupState]) -> list[BottomUpProteinGroup]:
        return [
            BottomUpProteinGroup(
                protein_group_id=identifier,
                source_group=state.source_group,
                member_protein_ids=state.member_protein_ids,
                leading_protein_id=state.leading_protein_id,
                identification_ids=tuple(sorted(state.identification_ids)),
                peptide_ids=tuple(sorted(state.peptide_ids)),
                q_value=state.q_value,
                pep=None,
                global_q_value=None,
                lib_q_value=None,
                quantification_ids=tuple(sorted(state.quantification_ids)),
                source_fields=state.source_fields,
            )
            for identifier, state in sorted(states.items())
        ]


def _read_tsv(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [
            {str(key): str(value or "") for key, value in row.items()}
            for row in csv.DictReader(stream, delimiter="\t")
        ]


def _read_fasta(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    identifier: str | None = None
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            text = line.strip()
            if not text:
                continue
            if text.startswith(">"):
                if identifier is not None:
                    _store_fasta(result, identifier, "".join(chunks).upper())
                identifier = text[1:].split(None, 1)[0]
                chunks = []
            else:
                chunks.append(text)
    if identifier is not None:
        _store_fasta(result, identifier, "".join(chunks).upper())
    return result


def _store_fasta(result: dict[str, str], identifier: str, sequence: str) -> None:
    result.setdefault(identifier, sequence)
    parts = identifier.split("|")
    if len(parts) >= 2 and parts[1]:
        result.setdefault(parts[1], sequence)


def _modifications(
    row: dict[str, str],
    *,
    identification_id: str,
    peptide_id: str,
    sequence: str,
    modified_sequence: str,
    protein_site_fields: dict[str, str],
    output: list[BottomUpModification],
) -> tuple[str, ...]:
    records: list[tuple[str, str, float, int, str, bool, float | None]] = []
    oxidation_sites = _oxidation_sites(sequence, modified_sequence)
    probabilities = _oxidation_probabilities(row.get("Oxidation (M) Probabilities"))
    for position in oxidation_sites:
        records.append(
            ("UNIMOD:35", "Oxidation (M)", 15.994915, position, "M", False, probabilities.get(position))
        )
    declared = _required_text(row, "Modifications")
    if declared != "Unmodified" and not re.fullmatch(r"(?:\d+ )?Oxidation \(M\)", declared):
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MODIFICATION_UNSUPPORTED",
            f"Unsupported observed modification declaration: {declared}",
        )
    result: list[str] = []
    for ordinal, (accession, name, mass, position, residue, fixed, probability) in enumerate(records, start=1):
        modification_id = _stable_id("modification", identification_id, accession, str(position), str(ordinal))
        output.append(
            BottomUpModification(
                modification_id=modification_id,
                identification_id=identification_id,
                peptide_id=peptide_id,
                token_ordinal=ordinal,
                accession=accession,
                name=name,
                mass_shift=mass,
                coordinate_system="peptide_1_based",
                position=position,
                residue=residue,
                terminal="NONE",
                is_fixed=fixed,
                localization_probability=probability,
                site_confidence=None,
                site_occupancy=None,
                source_protein_sites=protein_site_fields.get("Oxidation (M) site positions"),
                lib_site_confidence=None,
                source_fields={
                    "Modifications": declared,
                    "Modified sequence": modified_sequence,
                    "Oxidation (M) Probabilities": row.get("Oxidation (M) Probabilities"),
                    **protein_site_fields,
                },
            )
        )
        result.append(modification_id)
    return tuple(result)


def _group_modification_site_fields(
    groups: dict[str, _GroupState],
    group_ids: tuple[str, ...],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for field_name in (
        "Oxidation (M) site IDs",
        "Oxidation (M) site positions",
    ):
        values = {
            value
            for group_id in group_ids
            if (group := groups.get(group_id)) is not None
            if (value := _optional_text(group.source_fields.get(field_name))) is not None
        }
        if values:
            result[field_name] = ";".join(sorted(values))
    return result


def _oxidation_sites(sequence: str, modified_sequence: str) -> tuple[int, ...]:
    text = modified_sequence.strip("_")
    sites: list[int] = []
    position = 0
    cursor = 0
    while cursor < len(text):
        residue = text[cursor]
        if not residue.isalpha() or not residue.isupper():
            raise CompositeBottomUpConversionError(
                "COMPOSITE_MODIFIED_SEQUENCE_INVALID",
                f"Unsupported modified sequence syntax: {modified_sequence}",
            )
        position += 1
        if position > len(sequence) or sequence[position - 1] != residue:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_MODIFIED_SEQUENCE_INVALID",
                "Modified sequence does not reduce to Sequence",
            )
        cursor += 1
        if text.startswith(_OXIDATION_TOKEN, cursor):
            sites.append(position)
            cursor += len(_OXIDATION_TOKEN)
    if position != len(sequence):
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MODIFIED_SEQUENCE_INVALID",
            "Modified sequence does not reduce to Sequence",
        )
    return tuple(sites)


def _oxidation_probabilities(value: str | None) -> dict[int, float]:
    text = (value or "").strip()
    result: dict[int, float] = {}
    position = 0
    cursor = 0
    while cursor < len(text):
        residue = text[cursor]
        if not residue.isalpha() or not residue.isupper():
            return {}
        position += 1
        cursor += 1
        if cursor < len(text) and text[cursor] == "(":
            end = text.find(")", cursor + 1)
            if end < 0:
                return {}
            probability = _optional_finite(text[cursor + 1 : end])
            if residue == "M" and probability is not None and 0 <= probability <= 1:
                result[position] = probability
            cursor = end + 1
    return result


def _source_manifest(
    bundle: CompositeBottomUpBundle,
    source_file_hashes: dict[str, str],
) -> list[dict[str, Any]]:
    result = []
    for item in bundle.source_files:
        label = bundle.relative_label(item.path)
        digest = source_file_hashes.get(label)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise CompositeBottomUpConversionError(
                "MISSING_INPUT_SHA256",
                f"HashInput did not fingerprint source role {label}",
            )
        result.append(
            {
                "role": item.role,
                "source_file": label,
                "file_name": item.path.name,
                "size": item.path.stat().st_size,
                "sha256": digest,
                "processing_status": item.processing_status,
            }
        )
    return result


def _mqpar_parameters(path: Path) -> dict[str, Any]:
    wanted = {
        "maxQuantVersion",
        "enzymeMode",
        "maxMissedCleavages",
        "minPepLen",
        "maxCharge",
        "peptideFdr",
        "proteinFdr",
        "siteFdr",
        "decoyMode",
        "includeContaminants",
        "secondPeptide",
        "matchBetweenRuns",
        "reQuantify",
        "lfqMode",
        "ibaq",
        "top3",
        "multiplicity",
    }
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MQPAR_INVALID",
            "mqpar.xml cannot be parsed",
        ) from exc
    result: dict[str, Any] = {}
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        text = (element.text or "").strip()
        if name in wanted and text and name not in result:
            result[name] = text
    for container_name, target in (
        ("fixedModifications", "fixed_modifications"),
        ("variableModifications", "variable_modifications"),
        ("enzymes", "enzymes"),
    ):
        values: list[str] = []
        for container in root.iter():
            if container.tag.rsplit("}", 1)[-1] != container_name:
                continue
            values.extend(
                text
                for child in container
                if (text := (child.text or "").strip())
            )
        result[target] = values
    fasta_paths = [
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "fastaFilePath"
        and (element.text or "").strip()
    ]
    result["fasta_file_names"] = sorted({Path(item).name for item in fasta_paths})
    return result


def _validate_group_evidence_relations(
    group_rows: list[dict[str, str]],
    evidence_rows: list[dict[str, str]],
    evidence_ids: set[str],
) -> None:
    declared: dict[str, set[str]] = {}
    seen: list[str] = []
    for row in group_rows:
        group_id = _required_text(row, "id")
        group_evidence = set(_split(row.get("Evidence IDs")))
        declared[group_id] = group_evidence
        seen.extend(group_evidence)
    if len(seen) != len(set(seen)) or set(seen) != evidence_ids:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_EVIDENCE_PARTITION_INVALID",
            "proteinGroups Evidence IDs must form one exact partition of evidence.id",
        )
    reverse: dict[str, set[str]] = {key: set() for key in declared}
    for row in evidence_rows:
        evidence_id = _required_text(row, "id")
        for group_id in _split(row.get("Protein group IDs")):
            if group_id not in reverse:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_GROUP_REFERENCE_MISSING",
                    f"Evidence {evidence_id} references missing protein group {group_id}",
                )
            reverse[group_id].add(evidence_id)
    if reverse != declared:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_GROUP_EVIDENCE_RELATION_MISMATCH",
            "evidence Protein group IDs and proteinGroups Evidence IDs disagree",
        )


def _measurements(
    row: dict[str, str],
    columns: tuple[str, ...],
    *,
    include_null: bool = False,
) -> dict[str, float | str | None]:
    result: dict[str, float | str | None] = {}
    for name in columns:
        value = _optional_finite(row.get(name))
        if value is not None or include_null:
            result[re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")] = value
    return result


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "little"))
        digest.update(encoded)
    return f"{kind}:{digest.hexdigest()}"


def _required_text(row: dict[str, str], field: str) -> str:
    value = _optional_text(row.get(field))
    if value is None:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_ROW_INVALID",
            f"{field} must be non-empty",
        )
    return value


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _split(value: Any) -> tuple[str, ...]:
    text = value if isinstance(value, str) else ""
    return tuple(part.strip() for part in text.split(";") if part.strip())


def _optional_finite(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _required_nonnegative(value: Any, field: str) -> float:
    parsed = _optional_finite(value)
    if parsed is None or parsed < 0:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_ROW_INVALID",
            f"{field} must be finite and non-negative",
        )
    return parsed


def _positive_integer(value: Any, field: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_ROW_INVALID",
            f"{field} must be a positive integer",
        ) from exc
    if parsed <= 0:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_ROW_INVALID",
            f"{field} must be a positive integer",
        )
    return parsed


def _rt_seconds(row: dict[str, str], field: str, fallback: float) -> float:
    value = _optional_finite(row.get(field))
    return value * 60.0 if value is not None and value >= 0 else fallback


def _minimum(first: float | None, second: float | None) -> float | None:
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


def _protein_name(accession: str) -> str | None:
    parts = accession.split("|")
    return parts[2] if len(parts) >= 3 and parts[2] else None


def _external_sequence_allowed(accession: str) -> bool:
    return accession.startswith(("CON__", "REV__"))


def _sortable_id(value: Any) -> tuple[int, int | str]:
    text = str(value or "").strip()
    try:
        return 0, int(text)
    except ValueError:
        return 1, text
