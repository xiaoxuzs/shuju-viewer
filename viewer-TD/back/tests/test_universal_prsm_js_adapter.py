"""Unit tests for PrSM-js import aggregate metadata helpers."""

from __future__ import annotations

from app.ingest.universal_prsm_js_adapter import (
    _ProteinImportStats,
    _ProteoformImportStats,
    _consider_best_prsm,
    _record_prsm_for_stats,
)


def test_consider_best_prsm_picks_lowest_e_value() -> None:
    best_id, best_e = _consider_best_prsm(None, None, prsm_id=1, e_value=1e-3)
    assert best_id == 1
    assert best_e == 1e-3

    best_id, best_e = _consider_best_prsm(best_id, best_e, prsm_id=2, e_value=1e-5)
    assert best_id == 2
    assert best_e == 1e-5

    best_id, best_e = _consider_best_prsm(best_id, best_e, prsm_id=3, e_value=1e-4)
    assert best_id == 2
    assert best_e == 1e-5


def test_record_prsm_for_stats_aggregates_protein_and_proteoform() -> None:
    protein = _ProteinImportStats()
    form_a = _ProteoformImportStats()
    form_b = _ProteoformImportStats()

    _record_prsm_for_stats(
        protein_stats=protein,
        proteoform_stats=form_a,
        proteoform_id=101,
        source_prsm_id=1,
        e_value=1e-4,
    )
    _record_prsm_for_stats(
        protein_stats=protein,
        proteoform_stats=form_a,
        proteoform_id=101,
        source_prsm_id=2,
        e_value=1e-6,
    )
    _record_prsm_for_stats(
        protein_stats=protein,
        proteoform_stats=form_b,
        proteoform_id=102,
        source_prsm_id=3,
        e_value=1e-5,
    )

    assert protein.prsm_number == 3
    assert protein.proteoform_ids == {101, 102}
    assert protein.best_prsm_id == 2
    assert protein.best_prsm_e_value == 1e-6

    assert form_a.prsm_number == 2
    assert form_a.best_prsm_id == 2
    assert form_a.best_prsm_e_value == 1e-6

    assert form_b.prsm_number == 1
    assert form_b.best_prsm_id == 3
    assert form_b.best_prsm_e_value == 1e-5
