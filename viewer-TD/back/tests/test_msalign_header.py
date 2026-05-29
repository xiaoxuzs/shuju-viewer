"""Tests for TopFD msalign header parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.toppic_admission.msalign_header import (
    load_msalign_header_index,
    pick_precursor_feature_index,
    select_precursor_from_fields,
)

XZZ_MSALIGN = (
    Path(__file__).resolve().parents[2]
    / "test"
    / "xzx_PXD045330"
    / "topfd"
    / "20191118_rvg262_LT_110516-13_1000-1100_Techrep01_ms2.msalign"
)


def test_pick_precursor_feature_index_prefers_closest_mass() -> None:
    masses = [8671.448188, 7591.718635]
    assert pick_precursor_feature_index(masses, 8671.4606126714) == 0
    assert pick_precursor_feature_index(masses, 7591.7) == 1


def test_select_precursor_from_fields_multi_feature() -> None:
    mass, charge, mz = select_precursor_from_fields(
        precursor_mass_text="8671.448188:7591.718635",
        precursor_charge_text="8:7",
        precursor_mz_text="1084.938300:1085.538510",
        target_mass=8671.4606126714,
    )
    assert mass == pytest.approx(8671.448188)
    assert charge == 8
    assert mz == pytest.approx(1084.938300)


@pytest.mark.skipif(not XZZ_MSALIGN.is_file(), reason="xzx_PXD045330 sample not present")
def test_load_msalign_header_index_prsm32() -> None:
    index = load_msalign_header_index(XZZ_MSALIGN)
    header = index[389]
    assert header.scan == 705
    assert header.ms_one_scan == 701
    assert header.ms_one_id == 313

    mass, charge, mz = header.select_precursor(8671.4606126714)
    assert mass == pytest.approx(8671.448188)
    assert charge == 8
    assert mz == pytest.approx(1084.938300)


@pytest.mark.skipif(not XZZ_MSALIGN.is_file(), reason="xzx_PXD045330 sample not present")
def test_load_msalign_header_index_prsm9() -> None:
    index = load_msalign_header_index(XZZ_MSALIGN)
    header = index[158]
    assert header.scan == 240
    assert header.ms_one_scan == 236

    mass, charge, mz = header.select_precursor(11978.946359)
    assert mass == pytest.approx(11977.859009)
    assert charge == 11
    assert mz == pytest.approx(1089.903550)
