from __future__ import annotations

from app.bu.services.peptide_mapper import coverage_percent, find_peptide_occurrences, map_peptide, normalize_aa


def test_normalize_aa_strips_non_letters_and_uppercases() -> None:
    assert normalize_aa("K(UniMod:1)stg gkapr") == "KUNIMODSTGGKAPR"
    assert normalize_aa(None) == ""


def test_find_peptide_occurrences_returns_overlapping_matches() -> None:
    assert find_peptide_occurrences("AAAA", "AA") == [(0, 2), (1, 3), (2, 4)]


def test_map_peptide_marks_ambiguous_occurrences() -> None:
    mapped = map_peptide("MPEPTIDEPEPTIDE", "PEPTIDE")

    assert [(item.start, item.end) for item in mapped] == [(1, 8), (8, 15)]
    assert all(item.is_ambiguous for item in mapped)
    assert [item.occurrence_index for item in mapped] == [0, 1]


def test_histone_h4_known_segment_position() -> None:
    h4 = "MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALRE"

    assert find_peptide_occurrences(h4, "STGGKAPRKQL") == [(10, 21)]


def test_coverage_percent_merges_overlapping_intervals() -> None:
    assert coverage_percent(10, [(0, 4), (2, 7), (8, 10)]) == 0.9
    assert coverage_percent(10, []) == 0.0
    assert coverage_percent(0, [(0, 1)]) is None
