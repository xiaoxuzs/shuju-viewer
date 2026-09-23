"""Process-wide spectrum memory pool configuration (single source of truth)."""

from __future__ import annotations

import os

# Default 6 GiB for local single-process deployment.
_DEFAULT_MAX_BYTES = 6 * 1024**3


def max_capacity_bytes() -> int:
    raw = os.environ.get("VIEWER_SPECTRUM_MEMORY_MAX_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_BYTES
    return max(64 * 1024**2, int(raw))  # floor 64 MiB to avoid accidental tiny values
