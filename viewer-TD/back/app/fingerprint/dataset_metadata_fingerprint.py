"""Metadata-only dataset fingerprint (path + size + mtime per file, then MD5).

Matches the semantics of ``MD5-demo/fast_metadata_hash.py`` so duplicates are
detected without reading file contents. Intended to stay well under ~0.5s for
typical TopPIC trees when run on local SSD (validate with ``cs/`` benchmarks).
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Same exclusions as the demo script (do not hash the benchmark file itself).
_EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", "manifest_fast.json"})


@dataclass(frozen=True)
class MetadataFingerprintResult:
    """Result of :func:`compute_dataset_metadata_fingerprint`."""

    fingerprint: str
    """Lowercase 32-char hex MD5 of the sorted manifest text."""

    file_count: int
    elapsed_seconds: float


def compute_dataset_metadata_fingerprint(
    directory: Path | str,
    *,
    on_progress: Callable[[int], None] | None = None,
    progress_every_n_files: int = 500,
) -> MetadataFingerprintResult:
    """Walk *directory* (resolved), build manifest lines, return MD5 and stats.

    Each regular file contributes one line::

        <posix_relpath>|<size>|<mtime_ns_or_float>

    Lines are sorted lexicographically, joined with ``\\n``, UTF-8 encoded, and
    the MD5 digest of that byte string is returned (hex, lowercase).

    Symlinks are not followed. AppleDouble ``._*`` files are skipped.
    """
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    t0 = time.perf_counter()
    manifest_lines: list[str] = []
    file_count = 0
    root_s = str(root)

    def scan_dir(path: str) -> None:
        nonlocal file_count
        with os.scandir(path) as it:
            for entry in it:
                name = entry.name
                if name in _EXCLUDED_NAMES or name.startswith("._"):
                    continue
                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat()
                    rel = os.path.relpath(entry.path, root_s).replace(os.sep, "/")
                    line = f"{rel}|{stat.st_size}|{stat.st_mtime}"
                    manifest_lines.append(line)
                    file_count += 1
                    if on_progress is not None and progress_every_n_files > 0:
                        if file_count % progress_every_n_files == 0:
                            on_progress(file_count)
                elif entry.is_dir(follow_symlinks=False):
                    scan_dir(entry.path)

    scan_dir(root_s)
    manifest_lines.sort()
    manifest_content = "\n".join(manifest_lines)
    digest = hashlib.md5(manifest_content.encode("utf-8")).hexdigest()
    elapsed = time.perf_counter() - t0
    if on_progress is not None:
        on_progress(file_count)
    return MetadataFingerprintResult(fingerprint=digest, file_count=file_count, elapsed_seconds=elapsed)
