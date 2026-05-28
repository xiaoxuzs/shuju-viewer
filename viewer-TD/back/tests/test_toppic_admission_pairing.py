"""Tests for :mod:`app.toppic_admission.pairing`."""

from __future__ import annotations

from pathlib import Path

from app.toppic_admission.pairing import pair_pipeline_runs


def test_pair_single_run(tmp_path: Path) -> None:
    run = "20191118_rvg262_LT_110516-13_1000-1100_Techrep01"
    xml = tmp_path / "toppic" / f"{run}_ms2_toppic_prsm.xml"
    msalign = tmp_path / "topfd" / f"{run}_ms2.msalign"
    mzml = tmp_path / f"{run}.mzML"
    for path in (xml, msalign, mzml):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    result = pair_pipeline_runs(
        prsm_xml_files=(xml,),
        ms2_msalign_files=(msalign,),
        mzml_files=(mzml,),
    )

    assert result.reject_code is None
    assert len(result.triples) == 1
    assert result.triples[0].run_key == run.lower()
    assert result.triples[0].prsm_xml == xml
    assert result.triples[0].ms2_msalign == msalign
    assert result.triples[0].mzml == mzml


def test_pair_missing_msalign(tmp_path: Path) -> None:
    run = "runA"
    xml = tmp_path / "toppic" / f"{run}_ms2_toppic_prsm.xml"
    mzml = tmp_path / f"{run}.mzML"
    xml.parent.mkdir(parents=True)
    xml.write_text("x", encoding="utf-8")
    mzml.write_text("x", encoding="utf-8")

    result = pair_pipeline_runs(
        prsm_xml_files=(xml,),
        ms2_msalign_files=(),
        mzml_files=(mzml,),
    )

    assert result.triples == ()
    assert result.reject_code == "unpaired_run"
    assert "no matching *_ms2.msalign" in (result.reject_detail or "")


def test_pair_ambiguous_xml(tmp_path: Path) -> None:
    run = "runA"
    xml1 = tmp_path / "toppic" / f"{run}_ms2_toppic_prsm.xml"
    xml2 = tmp_path / "toppic" / f"{run}_toppic_prsm.xml"
    msalign = tmp_path / "topfd" / f"{run}_ms2.msalign"
    mzml = tmp_path / f"{run}.mzML"
    for path in (xml1, xml2, msalign, mzml):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    result = pair_pipeline_runs(
        prsm_xml_files=(xml1, xml2),
        ms2_msalign_files=(msalign,),
        mzml_files=(mzml,),
    )

    assert result.triples == ()
    assert result.reject_code == "ambiguous_pairing"
