"""Protein detail assembly for Bottom-Up sequence coverage."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.services.peptide_mapper import coverage_percent, map_peptide, normalize_aa
from app.bu.services.protein_sequence_resolver import resolve_base_sequence
from app.schemas import BuCoverageSegment, BuProteinDetailOut, BuProteinListItemOut, BuProteinPeptideRef
from app.zp_runtime import ZpBottomUpProtein, get_binary_bottom_up_protein


def get_protein_detail(session: Session, dataset: dict[str, Any], protein_id: int) -> BuProteinDetailOut | None:
    dataset_id = int(dataset["dataset_id"])
    protein = _protein_row(session, dataset_id, protein_id)
    if protein is None:
        return None

    binary = get_binary_bottom_up_protein(session, dataset_id, str(protein.get("accession") or ""))
    peptides = _peptide_rows(session, dataset_id, protein_id, include_decoy=bool(protein.get("is_decoy")))
    peptide_refs = [BuProteinPeptideRef(**_peptide_ref_payload(row)) for row in peptides]
    base_sequence, metadata = resolve_base_sequence(session, dataset, protein)
    if binary is not None:
        metadata = _binary_protein_metadata(metadata, binary)
        base_sequence = str(binary.protein.get("sequence") or base_sequence or "")
    normalized_sequence = normalize_aa(base_sequence)

    segments, mapped_intervals = _coverage_segments(normalized_sequence, peptides)
    mode = _coverage_mode(
        is_decoy=bool(protein.get("is_decoy")),
        has_sequence=bool(normalized_sequence),
        has_mapped=bool(mapped_intervals),
        has_unmapped=any(segment.start is None or segment.end is None for segment in segments),
    )
    percent = coverage_percent(len(normalized_sequence), mapped_intervals) if normalized_sequence else None

    list_payload = {key: protein[key] for key in BuProteinListItemOut.model_fields}
    if binary is not None:
        list_payload = _binary_protein_list_payload(list_payload, binary)
    list_item = BuProteinListItemOut(**list_payload)
    return BuProteinDetailOut(
        **list_item.model_dump(),
        base_sequence=normalized_sequence or None,
        coverage_mode=mode,
        coverage_percent=percent,
        coverage_segments=segments,
        peptides=peptide_refs,
        extra_metadata=metadata,
    )


def _protein_row(session: Session, dataset_id: int, protein_id: int) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT
                p.protein_id AS id,
                p.accession,
                p.gene_name,
                p.description,
                p.is_decoy,
                p.base_sequence,
                p.extra_metadata,
                jsonb_extract_path_text(p.extra_metadata, 'protein_group') AS protein_group,
                count(DISTINCT prm.entity_id) AS peptide_count,
                count(im.match_id) AS match_count,
                min(im.q_value) AS best_q_value,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'pg_max_lfq') AS double precision) AS pg_max_lfq,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'pg_q_value') AS double precision) AS pg_q_value,
                NULL::double precision AS pg_quantity
            FROM proteins p
            LEFT JOIN protein_relation_mapping prm
              ON prm.dataset_id = p.dataset_id
             AND prm.protein_id = p.protein_id
             AND prm.entity_type = 'PEPTIDE'
            LEFT JOIN identification_matches im
              ON im.dataset_id = prm.dataset_id
             AND im.entity_type = 'PEPTIDE'
             AND im.entity_id = prm.entity_id
            WHERE p.dataset_id = :dataset_id AND p.protein_id = :protein_id
            GROUP BY p.protein_id
            """
        ),
        {"dataset_id": dataset_id, "protein_id": protein_id},
    ).mappings().one_or_none()
    return dict(row) if row else None


def _peptide_rows(session: Session, dataset_id: int, protein_id: int, *, include_decoy: bool) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT
                pep.peptide_id,
                pep.sequence,
                count(im.match_id) AS match_count,
                min(im.q_value) AS best_q_value,
                (array_agg(im.match_id ORDER BY im.q_value ASC NULLS LAST, im.match_id ASC))[1] AS best_match_id,
                (array_agg(im.modified_sequence ORDER BY im.q_value ASC NULLS LAST, im.match_id ASC))[1]
                    AS modified_sequence
            FROM protein_relation_mapping prm
            JOIN peptides pep
              ON pep.dataset_id = prm.dataset_id
             AND pep.peptide_id = prm.entity_id
            LEFT JOIN identification_matches im
              ON im.dataset_id = prm.dataset_id
             AND im.entity_type = 'PEPTIDE'
             AND im.entity_id = prm.entity_id
             AND (:include_decoy OR im.is_decoy_match = false)
            WHERE prm.dataset_id = :dataset_id
              AND prm.protein_id = :protein_id
              AND prm.entity_type = 'PEPTIDE'
            GROUP BY pep.peptide_id
            ORDER BY best_q_value ASC NULLS LAST, pep.peptide_id ASC
            """
        ),
        {"dataset_id": dataset_id, "protein_id": protein_id, "include_decoy": include_decoy},
    ).mappings().all()
    return [dict(row) for row in rows]


def _coverage_segments(
    base_sequence: str,
    peptides: list[dict[str, Any]],
) -> tuple[list[BuCoverageSegment], list[tuple[int, int]]]:
    if not base_sequence:
        return [], []

    segments: list[BuCoverageSegment] = []
    intervals: list[tuple[int, int]] = []
    for peptide in peptides:
        occurrences = map_peptide(base_sequence, str(peptide.get("sequence") or ""))
        if not occurrences:
            segments.append(
                BuCoverageSegment(
                    peptide_id=int(peptide["peptide_id"]),
                    sequence=str(peptide.get("sequence") or ""),
                    match_count=int(peptide.get("match_count") or 0),
                    best_q_value=peptide.get("best_q_value"),
                )
            )
            continue
        for occurrence in occurrences:
            intervals.append((occurrence.start, occurrence.end))
            segments.append(
                BuCoverageSegment(
                    peptide_id=int(peptide["peptide_id"]),
                    sequence=str(peptide.get("sequence") or ""),
                    start=occurrence.start,
                    end=occurrence.end,
                    match_count=int(peptide.get("match_count") or 0),
                    best_q_value=peptide.get("best_q_value"),
                    is_ambiguous=occurrence.is_ambiguous,
                    occurrence_index=occurrence.occurrence_index,
                )
            )
    return segments, intervals


def _coverage_mode(
    *,
    is_decoy: bool,
    has_sequence: bool,
    has_mapped: bool,
    has_unmapped: bool,
) -> str:
    if is_decoy:
        return "decoy"
    if not has_sequence:
        return "list_only"
    if not has_mapped:
        return "list_only"
    return "partial" if has_unmapped else "full"


def _peptide_ref_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "peptide_id": int(row["peptide_id"]),
        "sequence": str(row.get("sequence") or ""),
        "modified_sequence": row.get("modified_sequence"),
        "match_count": int(row.get("match_count") or 0),
        "best_q_value": row.get("best_q_value"),
        "best_match_id": row.get("best_match_id"),
    }


def _binary_protein_list_payload(
    payload: dict[str, Any],
    binary: ZpBottomUpProtein,
) -> dict[str, Any]:
    protein = binary.protein
    out = dict(payload)
    out["accession"] = _first_value(protein.get("accession"), out.get("accession"))
    out["gene_name"] = _first_value(protein.get("gene"), protein.get("name"), out.get("gene_name"))
    out["description"] = _first_value(protein.get("description"), out.get("description"))
    out["is_decoy"] = bool(_first_value(protein.get("is_decoy"), out.get("is_decoy")))
    out["protein_group"] = _first_value(_joined_values(binary.protein_groups, "source_group"), out.get("protein_group"))
    out["peptide_count"] = len(binary.peptides)
    out["match_count"] = len(binary.identifications)
    out["best_q_value"] = _first_value(_best_bottom_up_q_value(binary.identifications), out.get("best_q_value"))
    out["pg_q_value"] = _first_value(protein.get("q_value"), out.get("pg_q_value"))
    return out


def _binary_protein_metadata(
    metadata: dict[str, Any],
    binary: ZpBottomUpProtein,
) -> dict[str, Any]:
    out = dict(metadata)
    protein = binary.protein
    updates = {
        "binary_protein_id": protein.get("protein_id"),
        "binary_peptide_ids": [item.get("peptide_id") for item in binary.peptides],
        "binary_identification_ids": [item.get("identification_id") for item in binary.identifications],
        "binary_protein_group_ids": [item.get("protein_group_id") for item in binary.protein_groups],
        "binary_q_value": protein.get("q_value"),
        "binary_quantification_count": len(binary.quantification),
    }
    for key, value in updates.items():
        if value is not None:
            out[key] = value
    return out


def _best_bottom_up_q_value(records: tuple[dict[str, Any], ...]) -> float | None:
    values = [_bottom_up_q_value(item) for item in records]
    values = [item for item in values if item is not None]
    return min(values) if values else None


def _bottom_up_q_value(record: dict[str, Any]) -> float | None:
    typed = record.get("typed_fields") if isinstance(record.get("typed_fields"), dict) else {}
    try:
        return float(typed.get("q_value")) if typed.get("q_value") is not None else None
    except (TypeError, ValueError):
        return None


def _joined_values(records: tuple[dict[str, Any], ...], field_name: str) -> str | None:
    values = [
        str(item.get(field_name)).strip()
        for item in records
        if item.get(field_name) is not None and str(item.get(field_name)).strip()
    ]
    unique = list(dict.fromkeys(values))
    return ";".join(unique) if unique else None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
