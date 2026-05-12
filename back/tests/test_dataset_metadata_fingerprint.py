"""Unit tests for :mod:`app.fingerprint.dataset_metadata_fingerprint`."""

from __future__ import annotations

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


def test_fingerprint_changes_when_content_changes(tmp_path: Path) -> None:
    f = tmp_path / "one.bin"
    f.write_bytes(b"hello")
    before = compute_dataset_metadata_fingerprint(tmp_path).fingerprint
    f.write_bytes(b"world")
    after = compute_dataset_metadata_fingerprint(tmp_path).fingerprint
    assert before != after


def test_excludes_noise_files(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("ok", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("junk", encoding="utf-8")
    r = compute_dataset_metadata_fingerprint(tmp_path)
    assert r.file_count == 1


def test_zero_files_empty_dir(tmp_path: Path) -> None:
    r = compute_dataset_metadata_fingerprint(tmp_path)
    assert r.file_count == 0
    assert r.fingerprint == "d41d8cd98f00b204e9800998ecf8427e"
