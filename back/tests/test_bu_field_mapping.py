from __future__ import annotations

from app.ingest.bu.field_mapping import should_import_match, split_protein_group, theoretical_mass_from_precursor


def test_should_import_match_uses_q_value_and_decoy() -> None:
    assert should_import_match({"Q.Value": 0.009, "Decoy": 0}) is True
    assert should_import_match({"Q.Value": 0.01, "Decoy": 0}) is False
    assert should_import_match({"Q.Value": 0.001, "Decoy": 1}) is False


def test_split_protein_group() -> None:
    assert split_protein_group("P1; P2;;P3") == ["P1", "P2", "P3"]


def test_theoretical_mass_from_precursor() -> None:
    mass = theoretical_mass_from_precursor(500.0, 2)
    assert mass is not None
    assert round(mass, 6) == round(500.0 * 2 - 1.007276466812 * 2, 6)
