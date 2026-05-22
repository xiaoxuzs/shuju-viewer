"""Runtime Bruker TDF root resolution."""

from __future__ import annotations

from pathlib import Path

from app.ingest.bu.run_discovery import resolve_bruker_tdf_root


def resolve_runtime_tdf_root(path: str | Path) -> Path:
    """Reuse ingest-time Bruker ``.d`` inner-root resolution."""
    return resolve_bruker_tdf_root(Path(path))

