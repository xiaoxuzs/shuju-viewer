from __future__ import annotations

from pathlib import Path

from app.services.prsm_files import ingest_root_has_supported_prsm_files


def _is_toppic_tree(root: Path) -> bool:
    toppic_cutoff_dirs = ("toppic_prsm_cutoff", "toppic_proteoform_cutoff")
    return any((root / cutoff_dir / "data_js" / "proteins.js").exists() for cutoff_dir in toppic_cutoff_dirs)


def test_toppic_tree_detection_accepts_prsm_cutoff(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")

    assert _is_toppic_tree(tmp_path)


def test_toppic_tree_detection_accepts_proteoform_cutoff(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_proteoform_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")

    assert _is_toppic_tree(tmp_path)


def test_ingest_root_detects_prsm_under_data(tmp_path: Path) -> None:
    prsm = tmp_path / "data" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    assert ingest_root_has_supported_prsm_files(tmp_path) is True


def test_ingest_root_detects_prsm_under_toppic_prsms(tmp_path: Path) -> None:
    prsm = tmp_path / "toppic_proteoform_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    assert ingest_root_has_supported_prsm_files(tmp_path) is True


def test_ingest_root_no_prsm_files(tmp_path: Path) -> None:
    assert ingest_root_has_supported_prsm_files(tmp_path) is False
