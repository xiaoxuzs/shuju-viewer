"""Tests for ``*.incoming`` → final dataset path relocation."""

from __future__ import annotations

from pathlib import Path

from app.services.incoming_path_relocate import relocate_incoming_root, try_fix_stale_incoming_absolute_path


def test_relocate_incoming_root_relative(tmp_path: Path) -> None:
    inc = tmp_path / "ds.incoming" / "sub"
    fin = tmp_path / "ds" / "sub"
    inc.mkdir(parents=True)
    fin.mkdir(parents=True)
    mz = inc / "a.mzML"
    mz.write_text("x", encoding="utf-8")
    fin_mz = fin / "a.mzML"
    fin_mz.write_text("x", encoding="utf-8")

    out = relocate_incoming_root(path=mz, incoming_root=tmp_path / "ds.incoming", final_root=tmp_path / "ds")
    assert Path(out) == fin_mz


def test_try_fix_stale_incoming_absolute_path(tmp_path: Path) -> None:
    final = tmp_path / "pkg" / "b.mzML"
    final.parent.mkdir(parents=True)
    final.write_text("m", encoding="utf-8")

    stale = tmp_path / "pkg.incoming" / "b.mzML"
    got = try_fix_stale_incoming_absolute_path(stale)
    assert got == final.resolve()
