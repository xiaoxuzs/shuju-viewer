"""Tests for TopPIC XML metadata loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.toppic_admission.toppic_xml_source import load_toppic_prsm_records

XZZ_XML = (
    Path(__file__).resolve().parents[2]
    / "test"
    / "xzx_PXD045330"
    / "toppic"
    / "20191118_rvg262_LT_110516-13_1000-1100_Techrep01_ms2_toppic_prsm.xml"
)


@pytest.mark.skipif(not XZZ_XML.is_file(), reason="xzx_PXD045330 sample not present")
def test_load_xzx_prsm_records() -> None:
    records = load_toppic_prsm_records(XZZ_XML)
    assert len(records) == 44
    assert records[0].prsm_id == 0
    assert records[0].sequence_name.startswith("sp|")
    assert records[0].annotated_seq


def test_load_minimal_xml(tmp_path: Path) -> None:
    xml = tmp_path / "sample_toppic_prsm.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<prsm_list>
<prsm>
  <prsm_id>7</prsm_id>
  <spectrum_id>12</spectrum_id>
  <spectrum_scan>197</spectrum_scan>
  <adjusted_prec_mass>12345.67</adjusted_prec_mass>
  <fdr>-1</fdr>
  <proteoform>
    <fasta_seq><seq_name>sp|TEST</seq_name><seq_desc>desc</seq_desc></fasta_seq>
    <prot_mod><name>NME</name></prot_mod>
    <start_pos>1</start_pos>
    <end_pos>5</end_pos>
    <proteo_cluster_id>3</proteo_cluster_id>
    <prot_id>9</prot_id>
    <proteo_match_seq>ACDEF</proteo_match_seq>
  </proteoform>
  <extreme_value><p_value>1e-3</p_value><e_value>2e-3</e_value></extreme_value>
</prsm>
</prsm_list>
""",
        encoding="utf-8",
    )
    records = load_toppic_prsm_records(xml)
    assert len(records) == 1
    assert records[0].prsm_id == 7
    assert records[0].n_acetylation is True
