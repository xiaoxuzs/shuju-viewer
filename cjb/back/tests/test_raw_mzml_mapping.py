from __future__ import annotations

from pathlib import Path

from app.ingest.bu.run_discovery import BuRunFile, match_diann_runs_to_files, normalize_diann_run_name
from app.services.mzml_mapping import build_one_to_one_mapping, normalize_spectrum_file_name


def test_raw_and_mzml_names_normalize_to_same_stem() -> None:
    assert normalize_spectrum_file_name("sample.raw") == "sample"
    assert normalize_spectrum_file_name("sample.RAW") == "sample"
    assert normalize_spectrum_file_name("sample.mzML") == "sample"
    assert normalize_spectrum_file_name("sample.mzml.gz") == "sample"
    assert normalize_diann_run_name("sample.raw") == "sample"


def test_toppic_prsm_raw_reference_matches_converted_mzml(tmp_path: Path) -> None:
    mzml = tmp_path / "sample.mzML"
    mzml.write_text("<mzML />", encoding="utf-8")

    mapping = build_one_to_one_mapping(
        spectrum_file_names={"sample.raw"},
        mzml_files=[mzml],
    )

    assert mapping == {"sample": mzml}


def test_diann_raw_run_value_matches_converted_mzml(tmp_path: Path) -> None:
    run = BuRunFile(tmp_path / "sample.mzML", "sample.mzML", "mzml", "sample")

    assert match_diann_runs_to_files({"sample.raw"}, [run]) == {"sample.raw": run}
