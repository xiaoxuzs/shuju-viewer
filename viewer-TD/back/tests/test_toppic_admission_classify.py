"""Tests for :mod:`app.toppic_admission.classify`."""

from __future__ import annotations

from pathlib import Path

from app.toppic_admission import AdmissionRoute, DirectIngestShape, classify_admission
from app.toppic_admission.reject import REJECT_BU_DIANN, REJECT_MISSING_MZML, REJECT_ONLY_MZML


def _write_pipeline_run(root: Path, *, run: str, with_mzml: bool = True) -> None:
    (root / "topfd").mkdir(parents=True, exist_ok=True)
    (root / "toppic").mkdir(parents=True, exist_ok=True)
    (root / "topfd" / f"{run}_ms2.msalign").write_text("msalign", encoding="utf-8")
    (root / "toppic" / f"{run}_ms2_toppic_prsm.xml").write_text("<xml />", encoding="utf-8")
    if with_mzml:
        (root / f"{run}.mzML").write_text("<mzML />", encoding="utf-8")


def test_classify_form_b_need_pfmb(tmp_path: Path) -> None:
    run = "20191118_rvg262_LT_110516-13_1000-1100_Techrep01"
    _write_pipeline_run(tmp_path, run=run)

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.NEED_PFMB
    assert len(decision.run_triples) == 1
    assert decision.pfmb_source is not None
    assert decision.pfmb_source.value == "xml_msalign"


def test_classify_form_b_missing_mzml_english_reason(tmp_path: Path) -> None:
    run = "runA"
    _write_pipeline_run(tmp_path, run=run, with_mzml=False)

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.UNSUPPORTED
    assert decision.reject_code == REJECT_MISSING_MZML
    assert decision.reject_reason is not None
    assert "No mzML spectra files were found" in decision.reject_reason


def test_classify_form_a_toppic_html(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.DIRECT_INGEST
    assert decision.direct_shape == DirectIngestShape.TOPPIC_HTML


def test_classify_form_a_prsm_bundle(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.DIRECT_INGEST
    assert decision.direct_shape == DirectIngestShape.PRSM_BUNDLE


def test_classify_prsm_files_without_known_layout(tmp_path: Path) -> None:
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.UNSUPPORTED
    assert "Supported PrSM detail files" in (decision.reject_reason or "")


def test_classify_only_mzml(tmp_path: Path) -> None:
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.UNSUPPORTED
    assert decision.reject_code == REJECT_ONLY_MZML
    assert "no supported prsm* files" in (decision.reject_reason or "").lower()


def test_classify_bu_diann_rejected(tmp_path: Path) -> None:
    report = tmp_path / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.UNSUPPORTED
    assert decision.reject_code == REJECT_BU_DIANN
    assert "DIA-NN Bottom-Up" in (decision.reject_reason or "")


def test_classify_data_dir_without_prsm_can_be_form_b(tmp_path: Path) -> None:
    run = "runA"
    (tmp_path / "data").mkdir()
    _write_pipeline_run(tmp_path, run=run)

    decision = classify_admission(tmp_path)

    assert decision.route == AdmissionRoute.NEED_PFMB
