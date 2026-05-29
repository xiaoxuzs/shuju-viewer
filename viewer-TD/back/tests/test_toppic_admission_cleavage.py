"""Tests for cleavage annotation assembly."""

from __future__ import annotations

from app.toppic_admission.cleavage import build_cleavage


def test_build_cleavage_marks_y_ions_on_c_term() -> None:
    peaks = [
        {
            "peak_id": "0",
            "spec_id": "1",
            "charge": "1",
            "matched_ions": {
                "matched_ion": [
                    {
                        "ion_type": "Y",
                        "ion_position": "12",
                        "ion_display_position": "12",
                    }
                ]
            },
        }
    ]
    cleavages = build_cleavage(peaks, protein_length=20)
    assert len(cleavages) == 21
    y_site = cleavages[8]
    assert y_site["position"] == "8"
    assert y_site["exist_c_ion"] == "1"
    assert y_site["exist_n_ion"] == "0"


def test_build_cleavage_marks_b_ions_on_n_term() -> None:
    peaks = [
        {
            "peak_id": "1",
            "spec_id": "1",
            "charge": "1",
            "matched_ions": {
                "matched_ion": [
                    {
                        "ion_type": "B",
                        "ion_position": "5",
                        "ion_display_position": "5",
                    }
                ]
            },
        }
    ]
    cleavages = build_cleavage(peaks, protein_length=10)
    site = cleavages[5]
    assert site["exist_n_ion"] == "1"
    assert site["exist_c_ion"] == "0"
