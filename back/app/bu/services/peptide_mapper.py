"""Peptide-to-protein sequence mapping helpers for Bottom-Up coverage."""

from __future__ import annotations

import re
from dataclasses import dataclass


_AA_RE = re.compile(r"[^A-Za-z]")


@dataclass(frozen=True)
class PeptideOccurrence:
    start: int
    end: int
    is_ambiguous: bool
    occurrence_index: int


def normalize_aa(value: str | None) -> str:
    """Normalize a peptide or protein sequence to uppercase letters only."""
    if not value:
        return ""
    return _AA_RE.sub("", value).upper()


def find_peptide_occurrences(protein: str, peptide: str) -> list[tuple[int, int]]:
    """Return every overlapping ``[start, end)`` occurrence of peptide in protein."""
    normalized_protein = normalize_aa(protein)
    normalized_peptide = normalize_aa(peptide)
    if not normalized_protein or not normalized_peptide:
        return []
    pattern = re.compile("(?=" + re.escape(normalized_peptide) + ")")
    return [(match.start(), match.start() + len(normalized_peptide)) for match in pattern.finditer(normalized_protein)]


def map_peptide(protein: str, peptide: str) -> list[PeptideOccurrence]:
    occurrences = find_peptide_occurrences(protein, peptide)
    ambiguous = len(occurrences) > 1
    return [
        PeptideOccurrence(start=start, end=end, is_ambiguous=ambiguous, occurrence_index=index)
        for index, (start, end) in enumerate(occurrences)
    ]


def coverage_percent(sequence_length: int, intervals: list[tuple[int, int]]) -> float | None:
    """Return covered residue fraction after merging all mapped intervals."""
    if sequence_length <= 0:
        return None
    valid = sorted((max(0, start), min(sequence_length, end)) for start, end in intervals if end > start)
    if not valid:
        return 0.0

    covered = 0
    cur_start, cur_end = valid[0]
    for start, end in valid[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            covered += cur_end - cur_start
            cur_start, cur_end = start, end
    covered += cur_end - cur_start
    return covered / sequence_length
