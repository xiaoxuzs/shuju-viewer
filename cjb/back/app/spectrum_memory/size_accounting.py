"""Byte estimates for pre-load eviction and post-load accounting."""

from __future__ import annotations

from pathlib import Path

from app.spectrum_memory.contracts import MzmlBundleSpec


def disk_bytes_for_paths(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += int(p.stat().st_size)
        except OSError:
            total += 0
    return total


def pre_load_reserve_bytes(spec: MzmlBundleSpec) -> int:
    """Conservative reservation before parsing (eviction planning)."""
    uniq: dict[str, Path] = {}
    for r in spec.runs:
        try:
            uniq[str(r.mzml_path.resolve())] = r.mzml_path
        except OSError:
            uniq[str(r.mzml_path)] = r.mzml_path
    disk = disk_bytes_for_paths(list(uniq.values()))
    # mzML XML expands in memory; multiplier is heuristic for eviction headroom.
    inflated = disk * 4
    # Per-run index / Python object overhead.
    overhead = max(0, len(spec.runs)) * 65_536
    return max(inflated + overhead, 1024 * 1024)
