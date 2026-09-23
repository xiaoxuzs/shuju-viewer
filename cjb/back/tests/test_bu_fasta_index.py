from __future__ import annotations

from pathlib import Path

from app.bu.services.fasta_index import (
    accession_from_fasta_header,
    candidate_accessions,
    description_from_fasta_header,
    discover_default_fasta,
    discover_unique_fasta,
    find_fasta_files,
    gene_name_from_fasta_header,
    load_fasta_index,
    load_fasta_record_index,
    lookup_fasta_record,
    settings,
)


def test_accession_from_uniprot_header() -> None:
    assert accession_from_fasta_header(">sp|P62805|H4_HUMAN Histone H4") == "P62805"
    assert accession_from_fasta_header(">CUSTOM_PROTEIN some description") == "CUSTOM_PROTEIN"


def test_uniprot_header_metadata() -> None:
    header = ">sp|P62805|H4_HUMAN Histone H4 OS=Homo sapiens OX=9606 GN=H4C1 PE=1 SV=2"

    assert description_from_fasta_header(header) == "Histone H4"
    assert gene_name_from_fasta_header(header) == "H4C1"


def test_load_fasta_index_joins_lines_and_normalizes(tmp_path: Path) -> None:
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(
        ">sp|P62805|H4_HUMAN Histone H4 OS=Homo sapiens OX=9606 GN=H4C1 PE=1 SV=2\n"
        "MARTKQTAR\nKSTG-GKAPR*\n",
        encoding="utf-8",
    )

    index = load_fasta_index(fasta)
    records = load_fasta_record_index(fasta)

    assert index["P62805"] == "MARTKQTARKSTGGKAPR"
    assert records["P62805"].description == "Histone H4"
    assert records["P62805"].gene_name == "H4C1"


def test_lookup_fasta_record_accepts_protein_groups(tmp_path: Path) -> None:
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(">sp|P62805|H4_HUMAN Histone H4\nMARTKQTAR\n", encoding="utf-8")
    records = load_fasta_record_index(fasta)

    assert candidate_accessions("sp|P11111|X;P62805") == ["P11111", "P62805"]
    assert lookup_fasta_record(records, "sp|P11111|X;P62805").sequence == "MARTKQTAR"


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


def test_discover_default_fasta_uses_configured_path(tmp_path: Path, monkeypatch) -> None:
    fasta = tmp_path / "human.fasta"
    fasta.write_text(">P1\nAAAA\n", encoding="utf-8")
    monkeypatch.setattr(settings, "bu_default_fasta_path", fasta)

    assert discover_default_fasta() == fasta.resolve()
