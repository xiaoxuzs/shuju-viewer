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
