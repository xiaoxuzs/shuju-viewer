"""Tests for :mod:`app.dataset_ingest_root.resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dataset_ingest_root import find_ingest_root, resolve_ingest_root
from app.dataset_ingest_root.resolver import has_bu_diann_layout, has_spectra_only_layout


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


def test_resolve_mzml_only_root(tmp_path: Path) -> None:
    root = tmp_path / "spectra"
    root.mkdir()
    (root / "run.mzML").write_text("<mzML />", encoding="utf-8")

    assert has_spectra_only_layout(root) is True
    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_raw_only_root(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "sample.RAW").write_bytes(b"raw")

    assert has_spectra_only_layout(root) is True
    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_mzml_with_thermo_parser_json_root(tmp_path: Path) -> None:
    root = tmp_path / "thermo-out"
    root.mkdir()
    (root / "sample.mzML").write_text("<mzML />", encoding="utf-8")
    (root / "sample.json").write_text("{}", encoding="utf-8")

    assert resolve_ingest_root(root) == root.resolve()


def test_resolve_prefers_nested_toppic_over_wrapper_mzml(tmp_path: Path) -> None:
    """Regression: a wrapper dir with no layout markers of its own, whose mzML lives deep
    inside the real (nested) TopPIC dataset dir, must resolve to the nested dir, not the
    wrapper — even though the wrapper alone looks like a spectra-only match (mzML found via
    recursive search)."""
    outer = tmp_path / "xzx_PXD045330"
    inner = outer / "xzx_PXD045330"
    _mkdir(inner / "data" / "prsms")
    (inner / "data" / "prsms" / "prsm1.js").write_text("{}", encoding="utf-8")
    mzml_dir = inner / "run.mzML"
    _mkdir(mzml_dir)
    (mzml_dir / "run.mzML").write_text("<mzML />", encoding="utf-8")

    assert has_spectra_only_layout(outer) is True
    assert resolve_ingest_root(outer) == inner.resolve()


def test_bruker_d_only_is_not_spectra_only(tmp_path: Path) -> None:
    root = tmp_path / "bruker"
    (root / "sample.d").mkdir(parents=True)

    assert has_spectra_only_layout(root) is False
    with pytest.raises(ValueError, match="supported dataset folder"):
        resolve_ingest_root(root)
