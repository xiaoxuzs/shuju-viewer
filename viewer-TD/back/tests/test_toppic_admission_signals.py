"""Tests for :mod:`app.toppic_admission.signals`."""

from __future__ import annotations

from pathlib import Path

from app.toppic_admission.signals import collect_signals


def _write_pipeline_run(root: Path, *, run: str, with_mzml: bool = True) -> None:
    (root / "topfd").mkdir(parents=True, exist_ok=True)
    (root / "toppic").mkdir(parents=True, exist_ok=True)
    (root / "topfd" / f"{run}_ms2.msalign").write_text("msalign", encoding="utf-8")
    (root / "toppic" / f"{run}_ms2_toppic_prsm.xml").write_text("<xml />", encoding="utf-8")
    if with_mzml:
        (root / f"{run}.mzML").write_text("<mzML />", encoding="utf-8")


def test_collect_signals_pipeline(tmp_path: Path) -> None:
    run = "20191118_rvg262_LT_110516-13_1000-1100_Techrep01"
    _write_pipeline_run(tmp_path, run=run)

    signals = collect_signals(tmp_path)

    assert signals.has_topfd is True
    assert signals.has_toppic_dir is True
    assert len(signals.prsm_xml_files) == 1
    assert len(signals.ms2_msalign_files) == 1
    assert len(signals.mzml_files) == 1
    assert signals.has_supported_prsm_files is False


def test_collect_signals_toppic_html(tmp_path: Path) -> None:
    proteins = tmp_path / "toppic_prsm_cutoff" / "data_js" / "proteins.js"
    proteins.parent.mkdir(parents=True, exist_ok=True)
    proteins.write_text("proteins = [];", encoding="utf-8")
    prsm = tmp_path / "toppic_prsm_cutoff" / "data_js" / "prsms" / "prsm1.js"
    prsm.parent.mkdir(parents=True, exist_ok=True)
    prsm.write_text("prsm_data = {};", encoding="utf-8")

    signals = collect_signals(tmp_path)

    assert signals.has_supported_prsm_files is True
    assert signals.prsm_file_count == 1
    assert signals.is_toppic_html_tree is True
