from __future__ import annotations

from pathlib import Path

import pytest

from app.services.import_planner import ImportLayoutError, plan_zip_ingest
from app.services.import_planner.types import DatasetShape


def test_plan_rejects_toppic_html_without_prsm(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")

    with pytest.raises(ImportLayoutError):
        plan_zip_ingest(tmp_path)


def test_plan_accepts_toppic_with_prsm_under_prsms(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    plan = plan_zip_ingest(tmp_path)
    assert plan.shape == DatasetShape.TOPPIC_HTML
    assert plan.spectra_source == "mzml_memory"
    assert plan.need_toppic_multirun_pass is True


def test_mzml_in_archive_prefers_mzml_over_partial_topfd(tmp_path: Path) -> None:
    """Full-style tree with mzML + a few spectrum*.js must not pick fragile topfd_js."""
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    mz = tmp_path / "run.mzML"
    mz.write_bytes(b"<mzML></mzML>")
    ms1 = tmp_path / "topfd" / "ms1_json"
    ms2 = tmp_path / "topfd" / "ms2_json"
    ms1.mkdir(parents=True, exist_ok=True)
    ms2.mkdir(parents=True, exist_ok=True)
    (ms1 / "spectrum1.js").write_text("{}", encoding="utf-8")
    (ms2 / "spectrum1.js").write_text("{}", encoding="utf-8")

    plan = plan_zip_ingest(tmp_path)
    assert plan.shape == DatasetShape.TOPPIC_HTML
    assert plan.spectra_source == "mzml_memory"
    assert plan.need_toppic_multirun_pass is True


def test_plan_prsm_bundle_requires_mzml_mode(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    plan = plan_zip_ingest(tmp_path)
    assert plan.shape == DatasetShape.PRSM_BUNDLE
    assert plan.spectra_source == "mzml_memory"
    assert plan.need_toppic_multirun_pass is False


def test_plan_prsm_bundle_accepts_prsm_under_data_prsms(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    mz = tmp_path / "run.mzML"
    mz.write_bytes(b"<mzML></mzML>")

    plan = plan_zip_ingest(tmp_path)
    assert plan.shape == DatasetShape.PRSM_BUNDLE
    assert plan.spectra_source == "mzml_memory"
    assert plan.need_toppic_multirun_pass is False


def test_plan_prsm_bundle_rejects_when_topfd_only_under_data_prsms(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    ms1 = tmp_path / "topfd" / "ms1_json"
    ms2 = tmp_path / "topfd" / "ms2_json"
    ms1.mkdir(parents=True, exist_ok=True)
    ms2.mkdir(parents=True, exist_ok=True)
    (ms1 / "spectrum1.js").write_text("{}", encoding="utf-8")
    (ms2 / "spectrum1.js").write_text("{}", encoding="utf-8")

    with pytest.raises(ImportLayoutError):
        plan_zip_ingest(tmp_path)


def test_plan_prsm_bundle_rejects_when_topfd_only(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    ms1 = tmp_path / "topfd" / "ms1_json"
    ms2 = tmp_path / "topfd" / "ms2_json"
    ms1.mkdir(parents=True, exist_ok=True)
    ms2.mkdir(parents=True, exist_ok=True)
    (ms1 / "spectrum1.js").write_text("{}", encoding="utf-8")
    (ms2 / "spectrum1.js").write_text("{}", encoding="utf-8")

    with pytest.raises(ImportLayoutError):
        plan_zip_ingest(tmp_path)


def test_plan_bu_diann_mixed(tmp_path: Path) -> None:
    report = tmp_path / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")
    d = tmp_path / "sample.d"
    d.mkdir()

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.DIANN_DIA
    assert plan.spectra_source == "mixed"
    assert plan.need_toppic_multirun_pass is False


def test_plan_accepts_mzml_only(tmp_path: Path) -> None:
    mzml = tmp_path / "sample.mzML"
    mzml.write_text("<mzML />", encoding="utf-8")
    (tmp_path / "sample.json").write_text("{}", encoding="utf-8")

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.MZML_ONLY
    assert plan.spectra_source == "mzml_memory"
    assert plan.mzml_files == (mzml.resolve(),)
    assert plan.contains_raw is False


def test_plan_keeps_toppic_priority_over_mzml_only(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.TOPPIC_HTML


def test_plan_accepts_toppic_native_output_with_gzipped_mzml(tmp_path: Path) -> None:
    toppic = tmp_path / "toppic"
    toppic.mkdir()
    (toppic / "run_ms2_toppic_prsm.xml").write_text(
        "<prsm_list><prsm /></prsm_list>",
        encoding="utf-8",
    )
    (toppic / "run_ms2.msalign").write_text("", encoding="utf-8")
    (tmp_path / "run.mzML.gz").write_bytes(b"gzip placeholder")

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.TOPPIC_NATIVE
    assert plan.spectra_source == "mzml_memory"
    assert plan.need_toppic_multirun_pass is False


def test_native_output_is_used_when_html_summary_lacks_prsm_details(
    tmp_path: Path,
) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    toppic = tmp_path / "toppic"
    toppic.mkdir()
    (toppic / "run_ms2_toppic_prsm.xml").write_text(
        "<prsm_list><prsm /></prsm_list>",
        encoding="utf-8",
    )
    (toppic / "run_ms2.msalign").write_text("", encoding="utf-8")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")

    assert plan_zip_ingest(tmp_path).shape == DatasetShape.TOPPIC_NATIVE
