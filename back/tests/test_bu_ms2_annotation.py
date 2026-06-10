from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bu.services import ms2_annotation_svc
from app.pfmb import MatchedIon, PfmbAnnotation


def _ion(
    *,
    peak_id: int,
    ion_type: str,
    ordinal: int,
    intensity: float,
) -> MatchedIon:
    return MatchedIon(
        ion_type=ion_type,
        fragment_ordinal=ordinal,
        charge=1,
        intensity=intensity,
        observed_neutral_mass=500.0 + peak_id,
        theoretical_neutral_mass=500.0 + peak_id,
        mass_error_ppm=0.5,
        mass_error_da=0.00025,
        peak_id=peak_id,
    )


def test_annotation_matrix_keeps_fragment_evidence_but_deduplicates_peak_intensity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = {
        10: PfmbAnnotation(
            prsm_index=10,
            scan=100,
            peptide="PEC[+57.021464]TIDE",
            matched_peak_count=2,
            matched_ions=[
                _ion(peak_id=1, ion_type="y", ordinal=5, intensity=10.0),
                _ion(peak_id=1, ion_type="b", ordinal=2, intensity=10.0),
                _ion(peak_id=2, ion_type="z_dot", ordinal=3, intensity=5.0),
            ],
        ),
        11: PfmbAnnotation(
            prsm_index=11,
            scan=101,
            peptide="PEC[+57.021464]TIDE",
            matched_peak_count=1,
            matched_ions=[_ion(peak_id=3, ion_type="b", ordinal=2, intensity=7.0)],
        ),
    }

    class FakeReader:
        def read(self, prsm_index: int) -> PfmbAnnotation:
            return annotations[prsm_index]

    monkeypatch.setattr(
        ms2_annotation_svc,
        "resolve_sidecar",
        lambda _extra: SimpleNamespace(pfmb_path=Path("results.pfmb")),
    )
    monkeypatch.setattr(ms2_annotation_svc, "_reader", lambda _path: FakeReader())

    dataset = {
        "capabilities": {"has_ms2_pfmb": True},
        "extra_metadata": {"ms2_annotation": {}},
    }
    match = {
        "extra_metadata": {
            "pfmb": {
                "apex_slot": 0,
                "slots": [
                    {"prsm_index": 10, "slot_index": 0, "slot_rt": 60.0},
                    {"prsm_index": 11, "slot_index": 1, "slot_rt": 65.0},
                ],
            }
        }
    }

    out = ms2_annotation_svc.get_annotation_matrix(dataset, match)
    row_by_key = {row.key: index for index, row in enumerate(out.fragments)}

    assert out.intensity[row_by_key["y5"]][0] == 10.0
    assert out.intensity[row_by_key["b2"]][0] == 10.0
    assert len(out.detected) == len(out.intensity)
    assert all(len(row) == len(out.slots) for row in out.detected)
    assert out.detected[row_by_key["y5"]] == [True, False]
    assert out.detected[row_by_key["b2"]] == [True, True]
    assert out.slot_summary[0].matched_ion_count == 3
    assert out.slot_summary[0].matched_peak_count == 2
    assert out.slot_summary[0].total_intensity == 15.0
    assert out.slot_summary[1].total_intensity == 7.0


def test_annotation_matrix_distinguishes_matched_zero_from_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = {
        10: PfmbAnnotation(
            prsm_index=10,
            scan=100,
            peptide="PEPTIDE",
            matched_peak_count=1,
            matched_ions=[_ion(peak_id=1, ion_type="y", ordinal=5, intensity=0.0)],
        ),
        11: PfmbAnnotation(
            prsm_index=11,
            scan=101,
            peptide="PEPTIDE",
            matched_peak_count=0,
            matched_ions=[],
        ),
    }

    class FakeReader:
        def read(self, prsm_index: int) -> PfmbAnnotation:
            return annotations[prsm_index]

    monkeypatch.setattr(
        ms2_annotation_svc,
        "resolve_sidecar",
        lambda _extra: SimpleNamespace(pfmb_path=Path("results.pfmb")),
    )
    monkeypatch.setattr(ms2_annotation_svc, "_reader", lambda _path: FakeReader())

    out = ms2_annotation_svc.get_annotation_matrix(
        {"capabilities": {"has_ms2_pfmb": True}, "extra_metadata": {"ms2_annotation": {}}},
        {
            "extra_metadata": {
                "pfmb": {
                    "apex_slot": 0,
                    "slots": [
                        {"prsm_index": 10, "slot_index": 0, "slot_rt": 60.0},
                        {"prsm_index": 11, "slot_index": 1, "slot_rt": 65.0},
                    ],
                }
            }
        },
    )

    assert out.intensity == [[0.0, 0.0]]
    assert out.detected == [[True, False]]
