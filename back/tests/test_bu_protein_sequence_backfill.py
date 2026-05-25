from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.bu.services.protein_sequence_backfill import backfill_protein_sequences_from_fasta


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_Result":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Conn:
    def __init__(self) -> None:
        self.rows = [
            {"protein_id": 1, "accession": "P62805", "base_sequence": None, "is_decoy": False},
            {"protein_id": 2, "accession": "DECOY_P62805", "base_sequence": None, "is_decoy": True},
            {"protein_id": 3, "accession": "P99999", "base_sequence": "EXISTING", "is_decoy": False},
            {"protein_id": 4, "accession": "P11111", "base_sequence": None, "is_decoy": False},
        ]
        self.updates: list[dict[str, Any]] = []
        self.dataset_stats: dict[str, Any] | None = None

    def execute(self, stmt: object, params: dict[str, Any]) -> _Result:
        sql = str(stmt)
        if "SELECT protein_id" in sql:
            return _Result(self.rows)
        if "UPDATE proteins" in sql:
            self.updates.append(params)
            return _Result([])
        if "UPDATE datasets" in sql:
            self.dataset_stats = json.loads(params["metadata"])["sequence_backfill"]
            return _Result([])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_backfill_updates_only_missing_non_decoy_proteins(tmp_path: Path) -> None:
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(">sp|P62805|H4_HUMAN\nMARTKQTAR\n", encoding="utf-8")
    conn = _Conn()

    stats = backfill_protein_sequences_from_fasta(conn, dataset_id=39, source_root=tmp_path)  # type: ignore[arg-type]

    assert stats["status"] == "completed"
    assert stats["matched"] == 1
    assert stats["missing"] == 1
    assert stats["skipped_decoy"] == 1
    assert stats["skipped_existing"] == 1
    assert conn.updates == [
        {
            "dataset_id": 39,
            "protein_id": 1,
            "sequence": "MARTKQTAR",
            "metadata": json.dumps({"sequence_source": "user_fasta", "sequence_length": 9}, ensure_ascii=False),
        }
    ]
    assert conn.dataset_stats == stats


def test_backfill_skips_when_fasta_is_not_unique(tmp_path: Path) -> None:
    (tmp_path / "one.fa").write_text(">P1\nAAAA\n", encoding="utf-8")
    (tmp_path / "two.fasta").write_text(">P2\nBBBB\n", encoding="utf-8")
    conn = _Conn()

    stats = backfill_protein_sequences_from_fasta(conn, dataset_id=39, source_root=tmp_path)  # type: ignore[arg-type]

    assert stats["status"] == "skipped"
    assert stats["reason"] == "no_unique_fasta"
    assert stats["fasta_count"] == 2
    assert conn.updates == []
    assert conn.dataset_stats == stats
