"""Integration-style tests for PFMB assemble using saved egress artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.services.prsm_files import get_prsm_root, load_prsm_document
from app.toppic_admission.assemble import assemble_all_from_egress
from app.toppic_admission.toppic_xml_source import load_toppic_prsm_records
from app.toppic_admission.validate import validate_adapted_staging

PFMB_WORK = Path(__file__).resolve().parents[2] / "test" / "pfmb_work"
XZZ_ROOT = Path(__file__).resolve().parents[2] / "test" / "xzx_PXD045330"
XZZ_XML = XZZ_ROOT / "toppic" / "20191118_rvg262_LT_110516-13_1000-1100_Techrep01_ms2_toppic_prsm.xml"
XZZ_MZML = XZZ_ROOT / "20191118_rvg262_LT_110516-13_1000-1100_Techrep01.mzML"


@pytest.mark.skipif(
    not (PFMB_WORK / "egress" / "_index.json").is_file() or not XZZ_XML.is_file(),
    reason="pfmb_work egress or xzx sample missing",
)
def test_assemble_from_saved_egress(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    egress = staging / "work" / "egress"
    egress.mkdir(parents=True)
    shutil.copytree(PFMB_WORK / "egress", egress, dirs_exist_ok=True)
    prsms_dir = staging / "data" / "prsms"
    prsms_dir.mkdir(parents=True)
    if XZZ_MZML.is_file():
        shutil.copy2(XZZ_MZML, staging / XZZ_MZML.name)

    xml_records = load_toppic_prsm_records(XZZ_XML)
    written = assemble_all_from_egress(
        xml_records=xml_records,
        egress_dir=egress,
        prsms_dir=prsms_dir,
        mzml_file_name=XZZ_MZML.name,
    )
    assert len(written) == 44
    validate_adapted_staging(staging)

    doc = load_prsm_document(prsms_dir / "prsm0.json")
    prsm = get_prsm_root(doc)
    assert prsm["ms"]["ms_header"]["spectrum_file_name"] == XZZ_MZML.name
    peaks = prsm["ms"]["peaks"]["peak"]
    assert isinstance(peaks, list) and peaks
    assert any(p.get("matched_ions", {}).get("matched_ion") for p in peaks)

    peaks0 = json.loads((egress / "prsm0_peaks.json").read_text(encoding="utf-8"))
    matched_rows = [r for r in peaks0["rows"] if r.get("matched")]
    assert int(prsm["matched_peak_number"]) == len(matched_rows)
