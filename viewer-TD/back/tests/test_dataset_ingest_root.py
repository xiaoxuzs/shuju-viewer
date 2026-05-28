"""Tests for :mod:`app.dataset_ingest_root.resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dataset_ingest_root import find_ingest_root, resolve_ingest_root
from app.dataset_ingest_root.resolver import has_bu_diann_layout, has_toppic_pipeline_layout


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def test_resolve_when_root_is_layout(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    _mkdir(root / "topfd")
    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_nested_single_child(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "wrapped"
    _mkdir(inner / "toppic_prsm_cutoff")
    assert resolve_ingest_root(outer) == inner.resolve()


def test_resolve_multiple_matches_errors(tmp_path: Path) -> None:
    outer = tmp_path / "bad"
    _mkdir(outer / "a" / "topfd")
    _mkdir(outer / "b" / "topfd")
    with pytest.raises(ValueError, match="Multiple"):
        resolve_ingest_root(outer)


def test_has_toppic_pipeline_layout(tmp_path: Path) -> None:
    root = tmp_path / "pipeline"
    (root / "topfd").mkdir(parents=True)
    (root / "toppic").mkdir(parents=True)
    (root / "topfd" / "run_ms2.msalign").write_text("x", encoding="utf-8")
    (root / "toppic" / "run_ms2_toppic_prsm.xml").write_text("<xml />", encoding="utf-8")

    assert has_toppic_pipeline_layout(root) is True
    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_bu_diann_root(tmp_path: Path) -> None:
    root = tmp_path / "diann"
    report = root / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    (root / "run.mzML").write_text("<mzML />", encoding="utf-8")

    assert has_bu_diann_layout(root) is True
    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_rejects_td_and_bu_same_root(tmp_path: Path) -> None:
    root = tmp_path / "mixed"
    _mkdir(root / "topfd")
    report = root / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    (root / "run.mzML").write_text("<mzML />", encoding="utf-8")

    with pytest.raises(ValueError, match="both TopPIC and DIA-NN"):
        find_ingest_root(root)
