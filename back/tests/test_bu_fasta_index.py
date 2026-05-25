from __future__ import annotations

from pathlib import Path

from app.bu.services.fasta_index import (
    accession_from_fasta_header,
    discover_unique_fasta,
    find_fasta_files,
    load_fasta_index,
)


def test_accession_from_uniprot_header() -> None:
    assert accession_from_fasta_header(">sp|P62805|H4_HUMAN Histone H4") == "P62805"
    assert accession_from_fasta_header(">CUSTOM_PROTEIN some description") == "CUSTOM_PROTEIN"


def test_load_fasta_index_joins_lines_and_normalizes(tmp_path: Path) -> None:
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(">sp|P62805|H4_HUMAN\nMARTKQTAR\nKSTG-GKAPR*\n", encoding="utf-8")

    index = load_fasta_index(fasta)

    assert index["P62805"] == "MARTKQTARKSTGGKAPR"


def test_discover_unique_fasta_requires_exactly_one_file(tmp_path: Path) -> None:
    assert discover_unique_fasta(tmp_path) is None

    fasta = tmp_path / "reference.fa"
    fasta.write_text(">P1\nAAAA\n", encoding="utf-8")
    assert discover_unique_fasta(tmp_path) == fasta
    assert find_fasta_files(tmp_path) == [fasta]

    other = tmp_path / "nested" / "other.fasta"
    other.parent.mkdir()
    other.write_text(">P2\nBBBB\n", encoding="utf-8")
    assert discover_unique_fasta(tmp_path) is None
