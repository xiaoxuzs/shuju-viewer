from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agent_import.source_sampling import MAX_FILES, MAX_SAMPLE_BYTES, MAX_SAMPLES, summarize_source_root


def test_source_summary_is_bounded_and_case_relative(tmp_path: Path) -> None:
    for index in range(MAX_FILES + 5):
        (tmp_path / f"sample-{index:03d}.txt").write_text("x" * (MAX_SAMPLE_BYTES + 50), encoding="utf-8")

    summary = summarize_source_root(tmp_path)

    assert summary["file_count"] == MAX_FILES
    assert summary["truncated"] is True
    assert len(summary["files"]) == MAX_FILES
    assert len(summary["samples"]) == MAX_SAMPLES
    assert all(not Path(item["relative_path"]).is_absolute() for item in summary["files"])
    assert all(len(item["content"].encode("utf-8")) <= MAX_SAMPLE_BYTES for item in summary["samples"])


def test_source_summary_does_not_follow_directory_links(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this Windows test host")

    summary = summarize_source_root(tmp_path)

    assert all(not str(item["relative_path"]).startswith("linked/") for item in summary["files"])
