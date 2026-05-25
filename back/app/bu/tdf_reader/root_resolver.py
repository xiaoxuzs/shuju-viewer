"""Runtime Bruker TDF root resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ingest.bu.run_discovery import resolve_bruker_tdf_root


def resolve_runtime_tdf_root(path: str | Path) -> Path:
    """Reuse ingest-time Bruker ``.d`` inner-root resolution."""
    return resolve_bruker_tdf_root(Path(path))


def resolve_run_tdf_root(run: dict[str, Any]) -> Path:
    """Resolve a DB run row to the effective Bruker TDF root."""
    metadata = run.get("run_metadata") if isinstance(run.get("run_metadata"), dict) else {}
    raw_path = metadata.get("tdf_path") or run.get("file_path")
    if not raw_path:
        raise ValueError("tdf_not_found")
    return resolve_runtime_tdf_root(Path(str(raw_path)))
