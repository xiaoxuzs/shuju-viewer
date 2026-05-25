"""Backfill Bottom-Up protein sequences from a local dataset FASTA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.bu.services.fasta_index import find_fasta_files, load_fasta_index, normalize_aa


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
        "missing": 0,
        "skipped_decoy": 0,
        "skipped_existing": 0,
    }
    if len(fasta_files) != 1:
        stats["status"] = "skipped"
        stats["reason"] = "no_unique_fasta"
        _write_dataset_stats(conn, dataset_id=dataset_id, stats=stats)
        return stats

    fasta_path = fasta_files[0]
    stats["status"] = "completed"
    stats["fasta_path"] = str(fasta_path)
    index = load_fasta_index(fasta_path)

    rows = conn.execute(
        text(
            """
            SELECT protein_id, accession, base_sequence, is_decoy
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
        if normalize_aa(row.get("base_sequence")):
            stats["skipped_existing"] += 1
            continue
        accession = str(row.get("accession") or "").strip().upper()
        sequence = normalize_aa(index.get(accession))
        if not sequence:
            stats["missing"] += 1
            continue
        conn.execute(
            text(
                """
                UPDATE proteins
                SET base_sequence = :sequence,
                    extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || CAST(:metadata AS jsonb)
                WHERE dataset_id = :dataset_id AND protein_id = :protein_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "protein_id": int(row["protein_id"]),
                "sequence": sequence,
                "metadata": json.dumps(
                    {"sequence_source": "user_fasta", "sequence_length": len(sequence)},
                    ensure_ascii=False,
                ),
            },
        )
        stats["matched"] += 1

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
