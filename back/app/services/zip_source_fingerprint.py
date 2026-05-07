"""Streaming fingerprint of uploaded import archives (ZIP bytes on disk).

Callers decide how to persist or interpret the digest; this module only reads
files and hashes them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_DEFAULT_CHUNK = 1024 * 1024  # 1 MiB, matches upload copy chunking in imports API


def sha256_hex_of_file(path: Path, *, chunk_size: int = _DEFAULT_CHUNK) -> str:
    """Return lowercase hex SHA-256 of the file at ``path`` without loading it whole."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
