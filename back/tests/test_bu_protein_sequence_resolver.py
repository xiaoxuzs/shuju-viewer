from __future__ import annotations

from pathlib import Path
from typing import Any

from app.bu.services import protein_sequence_resolver


class _Session:
    def __init__(self) -> None:
        self.statements: list[dict[str, Any]] = []

    def execute(self, _stmt: object, params: dict[str, Any]) -> None:
        self.statements.append(params)

    def commit(self) -> None:
        pass


def test_uniprot_disabled_does_not_fetch(monkeypatch) -> None:
    monkeypatch.setattr(protein_sequence_resolver.settings, "bu_uniprot_enabled", False)

    def fail_fetch(_accession: str) -> tuple[str | None, dict[str, Any]]:
        raise AssertionError("UniProt fetch should not be called when disabled")

    monkeypatch.setattr(protein_sequence_resolver, "_fetch_uniprot_cached", fail_fetch)

    sequence, metadata = protein_sequence_resolver.resolve_base_sequence(
        None,  # type: ignore[arg-type]
        {"dataset_id": 1, "source_root": ""},
        {"id": 2, "accession": "P62805", "is_decoy": False, "base_sequence": None, "extra_metadata": {}},
    )

    assert sequence is None
    assert metadata["sequence_source"] == "missing"
    assert metadata["sequence_fetch_error"] == "uniprot_disabled"


def test_unique_dataset_fasta_is_used_when_uniprot_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(protein_sequence_resolver.settings, "bu_uniprot_enabled", False)
    protein_sequence_resolver._FASTA_CACHE.clear()
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(">sp|P62805|H4_HUMAN Histone H4\nMARTKQTAR\nKSTGGKAPR\n", encoding="utf-8")
    session = _Session()

    sequence, metadata = protein_sequence_resolver.resolve_base_sequence(
        session,  # type: ignore[arg-type]
        {"dataset_id": 1, "source_root": str(tmp_path)},
        {"id": 2, "accession": "P62805", "is_decoy": False, "base_sequence": None, "extra_metadata": {}},
    )

    assert sequence == "MARTKQTARKSTGGKAPR"
    assert metadata["sequence_source"] == "user_fasta"
    assert session.statements[0]["sequence"] == "MARTKQTARKSTGGKAPR"


def test_default_fasta_is_used_when_dataset_has_no_fasta(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    fallback = tmp_path / "human.fasta"
    fallback.write_text(">sp|P62805|H4_HUMAN Histone H4\nMARTKQTAR\n", encoding="utf-8")
    monkeypatch.setattr(protein_sequence_resolver.settings, "bu_uniprot_enabled", False)
    monkeypatch.setattr(protein_sequence_resolver.settings, "bu_default_fasta_path", fallback)
    protein_sequence_resolver._FASTA_CACHE.clear()
    session = _Session()

    sequence, metadata = protein_sequence_resolver.resolve_base_sequence(
        session,  # type: ignore[arg-type]
        {"dataset_id": 1, "source_root": str(source_root)},
        {"id": 2, "accession": "P62805", "is_decoy": False, "base_sequence": None, "extra_metadata": {}},
    )

    assert sequence == "MARTKQTAR"
    assert metadata["sequence_source"] == "default_fasta"
    assert session.statements[0]["sequence"] == "MARTKQTAR"
