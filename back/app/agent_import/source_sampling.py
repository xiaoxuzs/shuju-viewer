"""Bounded, read-only source summaries for model context."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any


MAX_FILES = 200
MAX_SAMPLES = 8
MAX_SAMPLE_BYTES = 4_096
_TEXT_SUFFIXES = frozenset({".csv", ".json", ".md", ".tsv", ".txt", ".xml", ".yaml", ".yml"})


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _entry_is_link(entry: os.DirEntry[str]) -> bool:
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return entry.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_sample_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    current = root
    for part in relative.parts:
        current = current / part
        current.lstat()
        if current.is_symlink() or _is_reparse_point(current):
            raise ValueError("source sample may not traverse a link or junction")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("source sample escaped the Case source root") from exc
    if not resolved.is_file():
        raise ValueError("source sample is not a regular file")
    return resolved


def summarize_source_root(source_root: str | Path) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")

    files: list[dict[str, Any]] = []
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]
    while stack and len(files) < MAX_FILES:
        directory, relative_dir = stack.pop()
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda item: item.name.casefold(), reverse=True)
        for entry in ordered:
            relative = PurePosixPath(entry.name) if relative_dir == PurePosixPath(".") else relative_dir / entry.name
            if _entry_is_link(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append((Path(entry.path), relative))
            elif entry.is_file(follow_symlinks=False):
                stat_result = entry.stat(follow_symlinks=False)
                files.append(
                    {
                        "relative_path": relative.as_posix(),
                        "size_bytes": int(stat_result.st_size),
                        "suffix": Path(entry.name).suffix.casefold(),
                    }
                )
                if len(files) >= MAX_FILES:
                    break

    files.sort(key=lambda item: str(item["relative_path"]).casefold())
    samples: list[dict[str, Any]] = []
    for item in files:
        if len(samples) >= MAX_SAMPLES:
            break
        relative_path = str(item["relative_path"])
        path = _safe_sample_path(root, relative_path)
        suffix = str(item["suffix"])
        with path.open("rb") as stream:
            content = stream.read(MAX_SAMPLE_BYTES)
        if suffix in _TEXT_SUFFIXES:
            samples.append(
                {
                    "artifact_ref": f"source-sample://text/{relative_path}",
                    "relative_path": relative_path,
                    "sample_kind": "text",
                    "content": content.decode("utf-8", errors="replace"),
                }
            )
        else:
            samples.append(
                {
                    "artifact_ref": f"source-sample://binary-header/{relative_path}",
                    "relative_path": relative_path,
                    "sample_kind": "binary_header",
                    "hex": content[:64].hex(),
                }
            )
    return {
        "schema_version": 1,
        "file_count": len(files),
        "truncated": len(files) >= MAX_FILES,
        "files": files,
        "samples": samples,
    }
