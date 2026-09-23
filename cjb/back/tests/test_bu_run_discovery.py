from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.bu.run_discovery import (
    BuRunFile,
    discover_bu_runs,
    match_diann_runs_to_files,
    resolve_bruker_tdf_root,
)


def _valid_tdf(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "analysis.tdf").write_bytes(b"sqlite")
    (root / "analysis.tdf_bin").write_bytes(b"bin")


def test_resolve_bruker_tdf_root_uses_inner_wrapper(tmp_path: Path) -> None:
    outer = tmp_path / "sample.d"
    outer.mkdir()
    (outer / "analysis.tdf").write_bytes(b"")
    inner = outer / "sample.d"
    _valid_tdf(inner)

    assert resolve_bruker_tdf_root(outer) == inner.resolve()


def test_discover_bu_runs_dedupes_outer_and_inner_d(tmp_path: Path) -> None:
    (tmp_path / "run.mzML").write_text("<mzML />", encoding="utf-8")
    outer = tmp_path / "sample.d"
    outer.mkdir()
    (outer / "analysis.tdf").write_bytes(b"")
    _valid_tdf(outer / "sample.d")

    runs = discover_bu_runs(tmp_path)

    assert [r.raw_format for r in runs].count("mzml") == 1
    assert [r.raw_format for r in runs].count("bruker_d") == 1
    assert next(r for r in runs if r.raw_format == "bruker_d").file_path == (outer / "sample.d").resolve()


def test_match_diann_runs_to_files_requires_match_for_multiple_runs(tmp_path: Path) -> None:
    runs = [
        BuRunFile(tmp_path / "a.mzML", "a.mzML", "mzml", "a"),
        BuRunFile(tmp_path / "b.mzML", "b.mzML", "mzml", "b"),
    ]

    with pytest.raises(ValueError, match="did not match"):
        match_diann_runs_to_files({"c"}, runs)


def test_match_diann_runs_to_files_allows_single_run_fallback(tmp_path: Path) -> None:
    run = BuRunFile(tmp_path / "a.mzML", "a.mzML", "mzml", "a")

    assert match_diann_runs_to_files({"different"}, [run]) == {"different": run}
