from __future__ import annotations

from pathlib import Path

from app.dataset_ingest_root.resolver import has_bu_diann_layout
from app.services.import_planner import plan_zip_ingest
from app.services.import_planner.types import DatasetShape


def test_plan_accepts_diann_report_with_thermo_raw(tmp_path: Path) -> None:
    report = tmp_path / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")

    plan = plan_zip_ingest(tmp_path)

    assert has_bu_diann_layout(tmp_path) is True
    assert plan.shape == DatasetShape.DIANN_DIA
    assert plan.spectra_source == "mzml_memory"
    assert plan.contains_raw is True
    assert plan.raw_files == (raw.resolve(),)
    assert plan.raw_vendor == "thermo"
    assert plan.requires_raw_conversion is True


def test_plan_accepts_toppic_with_raw_backed_mzml_memory(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")
    raw = tmp_path / "sample.RAW"
    raw.write_bytes(b"raw")

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.TOPPIC_HTML
    assert plan.spectra_source == "mzml_memory"
    assert plan.contains_raw is True
    assert plan.raw_files == (raw.resolve(),)
    assert plan.need_toppic_multirun_pass is True


def test_plan_keeps_existing_bruker_d_behavior(tmp_path: Path) -> None:
    report = tmp_path / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")
    (tmp_path / "sample.d").mkdir()

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.DIANN_DIA
    assert plan.spectra_source == "mixed"
    assert plan.contains_raw is False


def test_plan_accepts_raw_only_as_mzml_only(tmp_path: Path) -> None:
    raw = tmp_path / "sample.RAW"
    raw.write_bytes(b"raw")

    plan = plan_zip_ingest(tmp_path)

    assert plan.shape == DatasetShape.MZML_ONLY
    assert plan.spectra_source == "mzml_memory"
    assert plan.contains_raw is True
    assert plan.raw_files == (raw.resolve(),)
    assert plan.raw_vendor == "thermo"
    assert plan.requires_raw_conversion is True
