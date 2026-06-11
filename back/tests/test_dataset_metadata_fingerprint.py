"""Unit tests for :mod:`app.fingerprint.dataset_metadata_fingerprint`."""

from __future__ import annotations

import builtins
import os
from pathlib import Path

import pytest

from app.fingerprint.dataset_metadata_fingerprint import compute_dataset_metadata_fingerprint


def test_fingerprint_stable_ordering(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    r1 = compute_dataset_metadata_fingerprint(tmp_path)
    r2 = compute_dataset_metadata_fingerprint(tmp_path)
    assert r1.fingerprint == r2.fingerprint
    assert r1.file_count == 2


def test_fingerprint_changes_when_nanosecond_mtime_changes(tmp_path: Path) -> None:
    f = tmp_path / "one.bin"
    f.write_bytes(b"hello")
    before = compute_dataset_metadata_fingerprint(tmp_path).fingerprint
    f.write_bytes(b"world")
    first_stat = f.stat()
    os.utime(
        f,
        ns=(
            first_stat.st_atime_ns,
            first_stat.st_mtime_ns + 1_000_000,
        ),
    )
    after = compute_dataset_metadata_fingerprint(tmp_path).fingerprint
    assert before != after


def test_fingerprint_does_not_read_large_mzml_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mzml = tmp_path / "large.mzML"
    with mzml.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)

    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fingerprint must not read file contents")

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(Path, "open", fail_open)

    result = compute_dataset_metadata_fingerprint(tmp_path)

    assert result.file_count == 1
    assert len(result.fingerprint) == 32


def test_excludes_noise_files(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("ok", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("junk", encoding="utf-8")
    r = compute_dataset_metadata_fingerprint(tmp_path)
    assert r.file_count == 1


def test_zero_files_empty_dir(tmp_path: Path) -> None:
    r = compute_dataset_metadata_fingerprint(tmp_path)
    assert r.file_count == 0
    assert r.fingerprint == "d41d8cd98f00b204e9800998ecf8427e"
