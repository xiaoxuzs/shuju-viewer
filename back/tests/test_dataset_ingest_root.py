"""Tests for :mod:`app.dataset_ingest_root.resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dataset_ingest_root import find_ingest_root, resolve_ingest_root


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
