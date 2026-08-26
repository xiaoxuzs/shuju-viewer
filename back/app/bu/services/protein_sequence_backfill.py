"""Backfill Bottom-Up protein sequences from a local dataset FASTA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.bu.services.fasta_index import (
    discover_default_fasta,
    find_fasta_files,
    load_fasta_record_index,
    lookup_fasta_record,
    normalize_aa,
)


def backfill_protein_sequences_from_fasta(
    conn: Connection,
    *,
    dataset_id: int,
    source_root: Path | str,
) -> dict[str, Any]:
    """Populate ``proteins.base_sequence`` from the unique FASTA under ``source_root``.

    Missing or non-unique FASTA files are recorded in stats and do not fail the caller.
    """
    root = Path(source_root)
    fasta_files = find_fasta_files(root)
    stats: dict[str, Any] = {
        "source": "user_fasta",
        "source_root": str(root),
        "fasta_path": None,
        "fasta_count": len(fasta_files),
        "matched": 0,
        "metadata_matched": 0,
        "missing": 0,
        "skipped_decoy": 0,
        "skipped_existing": 0,
    }
    if len(fasta_files) != 1:
        if fasta_files:
            stats["status"] = "skipped"
            stats["reason"] = "no_unique_fasta"
            _write_dataset_stats(conn, dataset_id=dataset_id, stats=stats)
            return stats
        fasta_path = discover_default_fasta()
        if fasta_path is None:
            stats["status"] = "skipped"
            stats["reason"] = "no_unique_fasta"
            _write_dataset_stats(conn, dataset_id=dataset_id, stats=stats)
            return stats
        stats["source"] = "default_fasta"
    else:
        fasta_path = fasta_files[0]

    stats["status"] = "completed"
    stats["fasta_path"] = str(fasta_path)
    index = load_fasta_record_index(fasta_path)
    sequence_source = str(stats["source"])

    rows = conn.execute(
        text(
            """
            SELECT protein_id, accession, gene_name, description, base_sequence, is_decoy
            FROM proteins
            WHERE dataset_id = :dataset_id
            ORDER BY protein_id
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()

    for row in rows:
        if bool(row.get("is_decoy")):
            stats["skipped_decoy"] += 1
            continue
        existing_sequence = normalize_aa(row.get("base_sequence"))
        existing_gene_name = _clean_text(row.get("gene_name"))
        existing_description = _clean_text(row.get("description"))
        if existing_sequence and existing_gene_name and existing_description:
            stats["skipped_existing"] += 1
            continue

        accession = str(row.get("accession") or "").strip()
        record = lookup_fasta_record(index, accession)
        if record is None:
            if existing_sequence:
                stats["skipped_existing"] += 1
            else:
                stats["missing"] += 1
            continue

        sequence = normalize_aa(record.sequence)
        gene_name = _clean_text(record.gene_name)
        description = _clean_text(record.description)
        update_sequence = not existing_sequence and bool(sequence)
        update_gene_name = not existing_gene_name and bool(gene_name)
        update_description = not existing_description and bool(description)
        if not update_sequence and not update_gene_name and not update_description:
            stats["skipped_existing"] += 1
            continue
        if not sequence and not existing_sequence:
            stats["missing"] += 1
            continue

        metadata = {
            "sequence_source": sequence_source,
            "sequence_length": len(sequence or existing_sequence),
        }
        if update_gene_name or update_description:
            metadata["protein_metadata_source"] = sequence_source
        conn.execute(
            text(
                """
                UPDATE proteins
                SET base_sequence = CASE WHEN :update_sequence THEN :sequence ELSE base_sequence END,
                    gene_name = CASE WHEN :update_gene_name THEN :gene_name ELSE gene_name END,
                    description = CASE WHEN :update_description THEN :description ELSE description END,
                    extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || CAST(:metadata AS jsonb)
                WHERE dataset_id = :dataset_id AND protein_id = :protein_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "protein_id": int(row["protein_id"]),
                "sequence": sequence,
                "gene_name": gene_name,
                "description": description,
                "update_sequence": update_sequence,
                "update_gene_name": update_gene_name,
                "update_description": update_description,
                "metadata": json.dumps(metadata, ensure_ascii=False),
            },
        )
        if update_sequence:
            stats["matched"] += 1
        if update_gene_name or update_description:
            stats["metadata_matched"] += 1

    _write_dataset_stats(conn, dataset_id=dataset_id, stats=stats)
    return stats


def _write_dataset_stats(conn: Connection, *, dataset_id: int, stats: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            UPDATE datasets
            SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || CAST(:metadata AS jsonb)
            WHERE dataset_id = :dataset_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "metadata": json.dumps({"sequence_backfill": stats}, ensure_ascii=False),
        },
    )


def _clean_text(value: Any) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None
