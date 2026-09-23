"""Project a strictly validated semantic ZP extension into the shared BU schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.decoy_truth import roll_up_decoy_values
from app.bu.services.peptide_mapper import map_peptide
from app.declarative_ingest import read_semantic_zp
from app.declarative_ingest.semantic_schema import SemanticDataset


@dataclass(frozen=True, slots=True)
class SemanticProjectionStats:
    proteins: int
    peptides: int
    identifications: int
    protein_relations: int
    exact_peptide_positions: int
    ambiguous_peptide_positions: int
    missing_peptide_positions: int

    def as_dict(self) -> dict[str, int]:
        return {
            "proteins": self.proteins,
            "peptides": self.peptides,
            "identifications": self.identifications,
            "protein_relations": self.protein_relations,
            "exact_peptide_positions": self.exact_peptide_positions,
            "ambiguous_peptide_positions": self.ambiguous_peptide_positions,
            "missing_peptide_positions": self.missing_peptide_positions,
        }


def project_semantic_zp(
    session: Session,
    *,
    dataset_id: int,
    zp_path: str | Path,
    run_id_by_semantic_id: dict[str, int],
) -> tuple[SemanticDataset, SemanticProjectionStats]:
    semantic = read_semantic_zp(zp_path)
    existing = _existing_entity_count(session, dataset_id)
    if existing:
        raise ValueError("semantic projection target already contains business entities")

    protein_db_ids = _insert_proteins(session, dataset_id, semantic)
    peptide_db_ids = _insert_peptides(session, dataset_id, semantic)
    _insert_identifications(
        session,
        dataset_id,
        semantic,
        run_id_by_semantic_id=run_id_by_semantic_id,
        peptide_db_ids=peptide_db_ids,
    )
    relation_counts = _insert_relations(
        session,
        dataset_id,
        semantic,
        protein_db_ids=protein_db_ids,
        peptide_db_ids=peptide_db_ids,
    )
    return semantic, SemanticProjectionStats(
        proteins=len(protein_db_ids),
        peptides=len(peptide_db_ids),
        identifications=len(semantic.identifications),
        protein_relations=sum(relation_counts.values()),
        exact_peptide_positions=relation_counts["DERIVED"],
        ambiguous_peptide_positions=relation_counts["AMBIGUOUS"],
        missing_peptide_positions=relation_counts["MISSING"],
    )


def _insert_proteins(session: Session, dataset_id: int, semantic: SemanticDataset) -> dict[str, int]:
    json_value = _json_value(session, "extra_metadata")
    statement = text(
        f"""
        INSERT INTO proteins (
            dataset_id, accession, gene_name, description,
            base_sequence, is_decoy, extra_metadata
        )
        VALUES (
            :dataset_id, :accession, :gene_name, :description,
            :base_sequence, :is_decoy, {json_value}
        )
        RETURNING protein_id
        """
    )
    result: dict[str, int] = {}
    for protein in semantic.proteins:
        row = session.execute(
            statement,
            {
                "dataset_id": dataset_id,
                "accession": protein.accession,
                "gene_name": protein.gene,
                "description": protein.description,
                "base_sequence": protein.sequence,
                # The legacy column is non-null on deployed schemas. Truth is retained in metadata.
                "is_decoy": bool(protein.is_decoy) if protein.is_decoy is not None else False,
                "extra_metadata": _json(
                    {
                        "semantic_protein_id": protein.protein_id,
                        "protein_name": protein.name,
                        "sequence_state": protein.sequence_state,
                        "is_decoy_state": "DIRECT" if protein.is_decoy is not None else "MISSING",
                        "source_fields": protein.source_fields,
                        "evidence_refs": protein.evidence_refs,
                    }
                ),
            },
        ).one()
        result[protein.protein_id] = int(row.protein_id)
    return result


def _insert_peptides(session: Session, dataset_id: int, semantic: SemanticDataset) -> dict[str, int]:
    json_value = _json_value(session, "extra_metadata")
    statement = text(
        f"""
        INSERT INTO peptides (
            dataset_id, sequence, theoretical_mass, length, extra_metadata
        )
        VALUES (
            :dataset_id, :sequence, NULL, :length, {json_value}
        )
        RETURNING peptide_id
        """
    )
    result: dict[str, int] = {}
    for peptide in semantic.peptides:
        row = session.execute(
            statement,
            {
                "dataset_id": dataset_id,
                "sequence": peptide.sequence,
                "length": len(peptide.sequence),
                "extra_metadata": _json(
                    {
                        "semantic_peptide_id": peptide.peptide_id,
                        "length_derivation": "peptide_sequence_length_v1",
                        "evidence_refs": peptide.evidence_refs,
                    }
                ),
            },
        ).one()
        result[peptide.peptide_id] = int(row.peptide_id)
    return result


def _insert_identifications(
    session: Session,
    dataset_id: int,
    semantic: SemanticDataset,
    *,
    run_id_by_semantic_id: dict[str, int],
    peptide_db_ids: dict[str, int],
) -> None:
    json_value = _json_value(session, "extra_metadata")
    statement = text(
        f"""
        INSERT INTO identification_matches (
            dataset_id, run_id, scan_number, spectrum_native_id,
            retention_time, ms_level, entity_type, entity_id,
            modified_sequence, experimental_mass, precursor_mz, precursor_charge,
            intensity, score, e_value, q_value, pep,
            is_decoy_match, search_engine,
            detail_path, detail_cache, extra_metadata
        )
        VALUES (
            :dataset_id, :run_id, :scan_number, :spectrum_native_id,
            :retention_time, :ms_level, 'PEPTIDE', :entity_id,
            :modified_sequence, :experimental_mass, :precursor_mz, :precursor_charge,
            :intensity, :score, NULL, :q_value, :pep,
            :is_decoy_match, NULL,
            NULL, NULL, {json_value}
        )
        """
    )
    quant_by_id = {item.quantification_id: item for item in semantic.quantification}
    modifications_by_id = {item.modification_id: item for item in semantic.modifications}
    proteins_by_id = {item.protein_id: item for item in semantic.proteins}
    groups_by_id = {item.protein_group_id: item for item in semantic.protein_groups}
    for identification in semantic.identifications:
        run_id = run_id_by_semantic_id.get(identification.run_id)
        peptide_id = peptide_db_ids.get(identification.peptide_id)
        if run_id is None or peptide_id is None:
            raise ValueError("semantic identification cannot be projected without its run and peptide")
        measurements = [
            quant_by_id[item]
            for item in identification.quantification_ids
            if item in quant_by_id
        ]
        unchannelled = [
            item
            for item in measurements
            if item.channel is None and item.unit in {"source_intensity", "intensity"}
        ]
        intensity = unchannelled[0].value if len(unchannelled) == 1 else None
        decoy_storage_value, decoy_state = roll_up_decoy_values(
            proteins_by_id[item].is_decoy if item in proteins_by_id else None
            for item in identification.protein_ids
        )
        group_names = [
            groups_by_id[item].source_group
            for item in identification.protein_group_ids
            if item in groups_by_id
        ]
        spectrum_available = identification.spectrum_link_state in {"DIRECT", "DERIVED"}
        session.execute(
            statement,
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "scan_number": (
                    identification.source_scan
                    if spectrum_available and identification.source_scan is not None
                    else -1
                ),
                "spectrum_native_id": identification.source_native_id if spectrum_available else None,
                "retention_time": identification.rt_seconds / 60.0 if identification.rt_seconds is not None else None,
                "ms_level": 2,
                "entity_id": peptide_id,
                "modified_sequence": identification.modified_sequence,
                "experimental_mass": identification.neutral_mass,
                "precursor_mz": identification.precursor_mz,
                "precursor_charge": identification.charge,
                "intensity": intensity,
                "score": identification.score,
                "q_value": identification.q_value,
                "pep": identification.pep,
                "is_decoy_match": decoy_storage_value,
                "extra_metadata": _json(
                    {
                        "semantic_identification_id": identification.identification_id,
                        "source_record_id": identification.source_record_id,
                        "source_scan": identification.source_scan,
                        "spectrum_link_state": identification.spectrum_link_state,
                        "ms_level_state": "DIRECT" if spectrum_available else "DERIVED",
                        "ms_level_derivation": None if spectrum_available else "bottom_up_psm_level_v1",
                        "scan_unavailable_reason": (
                            None if spectrum_available else "source spectrum relation is not available"
                        ),
                        "retention_time_source_unit": "second",
                        "retention_time_storage_unit": "minute",
                        "protein_group": ";".join(group_names) or None,
                        "protein_accessions": [
                            proteins_by_id[item].accession
                            for item in identification.protein_ids
                            if item in proteins_by_id
                        ],
                        "is_decoy_state": decoy_state,
                        "quantification": [item.model_dump(mode="json") for item in measurements],
                        "modifications": [
                            modifications_by_id[item].model_dump(mode="json")
                            for item in identification.modification_ids
                            if item in modifications_by_id
                        ],
                        "source_fields": identification.source_fields,
                        "evidence_refs": identification.evidence_refs,
                    }
                ),
            },
        )


def _insert_relations(
    session: Session,
    dataset_id: int,
    semantic: SemanticDataset,
    *,
    protein_db_ids: dict[str, int],
    peptide_db_ids: dict[str, int],
) -> dict[str, int]:
    json_value = _json_value(session, "extra_metadata")
    statement = text(
        f"""
        INSERT INTO protein_relation_mapping (
            dataset_id, protein_id, entity_type, entity_id,
            start_position, end_position, is_unique, extra_metadata
        )
        VALUES (
            :dataset_id, :protein_id, 'PEPTIDE', :entity_id,
            :start_position, :end_position, :is_unique, {json_value}
        )
        """
    )
    proteins = {item.protein_id: item for item in semantic.proteins}
    peptides = {item.peptide_id: item for item in semantic.peptides}
    pairs = {
        (item.left_id, item.right_id)
        for item in semantic.relationships
        if item.kind == "peptide_to_protein" and item.state in {"DIRECT", "DERIVED"} and item.right_id
    }
    counts = {"DERIVED": 0, "AMBIGUOUS": 0, "MISSING": 0}
    for peptide_id, protein_id in sorted(pairs):
        protein = proteins.get(protein_id)
        peptide = peptides.get(peptide_id)
        protein_db_id = protein_db_ids.get(protein_id)
        peptide_db_id = peptide_db_ids.get(peptide_id)
        if protein is None or peptide is None or protein_db_id is None or peptide_db_id is None:
            raise ValueError("semantic peptide-to-protein relationship references a missing entity")
        occurrences = map_peptide(protein.sequence or "", peptide.sequence) if protein.sequence else []
        if len(occurrences) == 1:
            position_state = "DERIVED"
            start_position = occurrences[0].start
            end_position = occurrences[0].end
            is_unique = True
            derivation = "exact_peptide_substring_v1"
        elif len(occurrences) > 1:
            position_state = "AMBIGUOUS"
            start_position = None
            end_position = None
            is_unique = False
            derivation = None
        else:
            position_state = "MISSING"
            start_position = None
            end_position = None
            is_unique = False
            derivation = None
        counts[position_state] += 1
        session.execute(
            statement,
            {
                "dataset_id": dataset_id,
                "protein_id": protein_db_id,
                "entity_id": peptide_db_id,
                "start_position": start_position,
                "end_position": end_position,
                "is_unique": is_unique,
                "extra_metadata": _json(
                    {
                        "source": "viewer_semantic_dataset",
                        "position_state": position_state,
                        "position_derivation": derivation,
                    }
                ),
            },
        )
    return counts


def _existing_entity_count(session: Session, dataset_id: int) -> int:
    total = 0
    for table in ("proteins", "peptides", "identification_matches"):
        total += int(
            session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            or 0
        )
    return total


def _json_value(session: Session, parameter: str) -> str:
    return f"CAST(:{parameter} AS jsonb)" if session.get_bind().dialect.name == "postgresql" else f":{parameter}"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
