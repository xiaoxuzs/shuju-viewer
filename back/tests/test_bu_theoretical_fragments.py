from __future__ import annotations

from pathlib import Path

import pytest
from pyteomics import mass

from app.bu.services.modified_sequence import (
    ModifiedSequenceError,
    parse_modified_sequence,
)
from app.bu.services.theoretical_fragments import match_by_ions


CARBAMIDOMETHYL_DELTA = 57.021464
OXIDATION_DELTA = 15.994915


def _write_unimod_xml(path: Path, records: list[tuple[str, str]]) -> Path:
    modifications = "".join(
        f'<umod:mod record_id="{record_id}"><umod:delta mono_mass="{delta}"/></umod:mod>'
        for record_id, delta in records
    )
    path.write_text(
        '<umod:unimod xmlns:umod="http://www.unimod.org/xmlns/schema/unimod_2">'
        f"<umod:modifications>{modifications}</umod:modifications>"
        "</umod:unimod>",
        encoding="utf-8",
    )
    return path


def _mz(sequence: str, *, ion_type: str, charge: int) -> float:
    return float(mass.fast_mass(sequence, ion_type=ion_type, charge=charge))


def _matched_mz_by_ion(
    *,
    sequence: str,
    modified_sequence: str | None,
    peaks: list[float],
) -> dict[tuple[str, int, int], float]:
    matches = match_by_ions(
        sequence=sequence,
        modified_sequence=modified_sequence,
        mz=peaks,
        intensity=[1000.0 + index for index in range(len(peaks))],
        ppm=1.0,
    )
    return {
        (ion.ion_type, ion.position, ion.charge): ion.theo_mz
        for ion in matches
    }


def test_modified_residue_shifts_only_fragments_that_contain_the_site() -> None:
    sequence = "ACDE"
    expected = {
        ("b", 1, 1): _mz("A", ion_type="b", charge=1),
        ("b", 2, 1): _mz("AC", ion_type="b", charge=1) + CARBAMIDOMETHYL_DELTA,
        ("b", 2, 2): _mz("AC", ion_type="b", charge=2) + CARBAMIDOMETHYL_DELTA / 2,
        ("y", 2, 1): _mz("DE", ion_type="y", charge=1),
        ("y", 3, 1): _mz("CDE", ion_type="y", charge=1) + CARBAMIDOMETHYL_DELTA,
    }

    actual = _matched_mz_by_ion(
        sequence=sequence,
        modified_sequence="AC(UniMod:4)DE",
        peaks=list(expected.values()),
    )

    assert actual.keys() == expected.keys()
    for ion, expected_mz in expected.items():
        assert actual[ion] == pytest.approx(expected_mz, abs=1e-9)


def test_multiple_modifications_accumulate_and_scale_by_charge() -> None:
    sequence = "ACMDE"
    both_deltas = CARBAMIDOMETHYL_DELTA + OXIDATION_DELTA
    expected = {
        ("b", 3, 1): _mz("ACM", ion_type="b", charge=1) + both_deltas,
        ("b", 3, 2): _mz("ACM", ion_type="b", charge=2) + both_deltas / 2,
        ("y", 3, 1): _mz("MDE", ion_type="y", charge=1) + OXIDATION_DELTA,
        ("y", 4, 2): _mz("CMDE", ion_type="y", charge=2) + both_deltas / 2,
    }

    actual = _matched_mz_by_ion(
        sequence=sequence,
        modified_sequence="AC(UniMod:4)M(UniMod:35)DE",
        peaks=list(expected.values()),
    )

    assert actual.keys() == expected.keys()
    for ion, expected_mz in expected.items():
        assert actual[ion] == pytest.approx(expected_mz, abs=1e-9)


def test_parser_locates_modification_on_the_correct_residue() -> None:
    parsed = parse_modified_sequence(
        "AAAGEFADDPC(UniMod:4)SSVK",
        expected_sequence="AAAGEFADDPCSSVK",
    )

    assert parsed.sequence == "AAAGEFADDPCSSVK"
    assert parsed.modification_count == 1
    assert parsed.residue_deltas[10] == pytest.approx(CARBAMIDOMETHYL_DELTA)
    assert sum(parsed.residue_deltas[:10]) == 0.0
    assert parsed.b_delta(10) == 0.0
    assert parsed.b_delta(11) == pytest.approx(CARBAMIDOMETHYL_DELTA)
    assert parsed.y_delta(4) == 0.0
    assert parsed.y_delta(5) == pytest.approx(CARBAMIDOMETHYL_DELTA)


def test_leading_n_terminal_modification_only_shifts_b_ions() -> None:
    n_terminal_delta = 42.010565
    expected = {
        ("b", 1, 1): _mz("P", ion_type="b", charge=1) + n_terminal_delta,
        ("b", 2, 2): _mz("PE", ion_type="b", charge=2) + n_terminal_delta / 2,
        ("y", 2, 1): _mz("DE", ion_type="y", charge=1),
    }

    actual = _matched_mz_by_ion(
        sequence="PEPTIDE",
        modified_sequence="_(UniMod:1)PEPTIDE_",
        peaks=list(expected.values()),
    )

    assert actual.keys() == expected.keys()
    for ion, expected_mz in expected.items():
        assert actual[ion] == pytest.approx(expected_mz, abs=1e-9)


@pytest.mark.parametrize(
    ("modified_sequence", "expected_sequence", "error_code"),
    [
        ("AC[UniMod:4]DE", "ACDE", "modified_sequence_invalid"),
        ("AC(UniMod:4)DF", "ACDE", "modified_sequence_mismatch"),
        ("AC(UniMod:999999)DE", "ACDE", "unimod_id_unknown"),
        ("AC(UniMod:)DE", "ACDE", "modified_sequence_invalid"),
    ],
)
def test_unsupported_or_inconsistent_modified_sequence_fails_closed(
    modified_sequence: str,
    expected_sequence: str,
    error_code: str,
) -> None:
    with pytest.raises(ModifiedSequenceError) as exc:
        parse_modified_sequence(
            modified_sequence,
            expected_sequence=expected_sequence,
        )

    assert exc.value.code == error_code


def test_unmodified_sequence_does_not_require_unimod_snapshot(tmp_path: Path) -> None:
    parsed = parse_modified_sequence(
        "ACDE",
        expected_sequence="ACDE",
        unimod_xml_path=tmp_path / "missing.xml",
    )

    assert not parsed.has_modifications
    assert parsed.residue_deltas == (0.0, 0.0, 0.0, 0.0)


def test_modified_sequence_fails_closed_when_unimod_snapshot_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ModifiedSequenceError) as exc:
        parse_modified_sequence(
            "AC(UniMod:4)DE",
            expected_sequence="ACDE",
            unimod_xml_path=tmp_path / "missing.xml",
        )

    assert exc.value.code == "unimod_mass_source_unavailable"


def test_negative_monoisotopic_delta_is_preserved(tmp_path: Path) -> None:
    xml_path = _write_unimod_xml(tmp_path / "unimod.xml", [("900001", "-17.026549")])

    parsed = parse_modified_sequence(
        "A(UniMod:900001)C",
        expected_sequence="AC",
        unimod_xml_path=xml_path,
    )

    assert parsed.residue_deltas == pytest.approx((-17.026549, 0.0))


@pytest.mark.parametrize(
    "records",
    [
        [("not-an-id", "57.0")],
        [("4", "nan")],
        [("4", "not-a-mass")],
    ],
)
def test_invalid_unimod_mass_entries_fail_closed(
    tmp_path: Path,
    records: list[tuple[str, str]],
) -> None:
    xml_path = _write_unimod_xml(tmp_path / "unimod.xml", records)

    with pytest.raises(ModifiedSequenceError) as exc:
        parse_modified_sequence(
            "AC(UniMod:4)DE",
            expected_sequence="ACDE",
            unimod_xml_path=xml_path,
        )

    assert exc.value.code == "unimod_mass_source_unavailable"


def test_corrupt_unimod_xml_fails_closed(tmp_path: Path) -> None:
    xml_path = tmp_path / "unimod.xml"
    xml_path.write_text("<not-closed>", encoding="utf-8")

    with pytest.raises(ModifiedSequenceError) as exc:
        parse_modified_sequence(
            "AC(UniMod:4)DE",
            expected_sequence="ACDE",
            unimod_xml_path=xml_path,
        )

    assert exc.value.code == "unimod_mass_source_unavailable"
