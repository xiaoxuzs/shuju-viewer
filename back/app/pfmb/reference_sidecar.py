"""Resolve pre-built PFMB v2 sidecars (Hela-style full RT expansion)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.pfmb.index_builder import (
    build_index_json_from_pos_pkl,
    count_pos_pkl_expansion,
    read_pfmb_record_count,
)
from app.pfmb.locator import detect_sidecar


def sidecar_candidate_dirs(root: Path) -> list[Path]:
    """Return sidecar directories under *root* (``root`` or ``root/data``)."""

    resolved = root.resolve()
    out: list[Path] = []
    for candidate in (resolved, resolved / "data"):
        if detect_sidecar(candidate) is not None:
            out.append(candidate)
    return out


def is_v2_sidecar_for_pos_pkl(sidecar_dir: Path, pos_pkl: Path) -> bool:
    """True when ``results.pfmb`` record count matches *pos_pkl* RT slot expansion."""

    if detect_sidecar(sidecar_dir) is None:
        return False
    try:
        source_rows, expanded = count_pos_pkl_expansion(pos_pkl)
        pfmb_count = read_pfmb_record_count(sidecar_dir / "results.pfmb")
    except (OSError, ValueError):
        return False
    if pfmb_count != expanded:
        return False
    manifest_counts = _manifest_counts(sidecar_dir)
    if manifest_counts is not None:
        if manifest_counts.get("expanded_records") not in (None, expanded):
            return False
        if manifest_counts.get("source_rows") not in (None, source_rows):
            return False
    return True


def find_reference_v2_sidecar(pos_pkl: Path, reference_roots: list[Path]) -> Path | None:
    """Return the first reference sidecar whose PFMB matches *pos_pkl* v2 expansion."""

    for root in reference_roots:
        if not root.is_dir():
            continue
        for sidecar_dir in sidecar_candidate_dirs(root):
            if is_v2_sidecar_for_pos_pkl(sidecar_dir, pos_pkl):
                return sidecar_dir.resolve()
    return None


def materialize_v2_sidecar(
    *,
    reference_dir: Path,
    output_dir: Path,
    pos_pkl: Path,
) -> Path:
    """Copy a validated v2 ``results.pfmb`` and rebuild ``index.json`` for *pos_pkl*."""

    reference_dir = reference_dir.resolve()
    if not is_v2_sidecar_for_pos_pkl(reference_dir, pos_pkl):
        raise ValueError(f"reference sidecar is not v2-compatible with {pos_pkl}")

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(reference_dir / "results.pfmb", output_dir / "results.pfmb")
    source_rows, expanded = count_pos_pkl_expansion(pos_pkl)
    build_index_json_from_pos_pkl(
        pos_pkl,
        output_dir / "index.json",
        expected_record_count=source_rows,
        expected_expanded_record_count=expanded,
    )
    return output_dir.resolve()


def _manifest_counts(sidecar_dir: Path) -> dict[str, int] | None:
    for name in ("generation_manifest.json", "prsm.v2.manifest.json"):
        path = sidecar_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        counts = payload.get("counts")
        if isinstance(counts, dict):
            return _normalize_counts(counts)
    return None


def _normalize_counts(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("expanded_records", "source_rows", "input_rows", "written"):
        value = raw.get(key)
        if isinstance(value, int):
            out[key] = value
    if "expanded_records" not in out and isinstance(raw.get("written"), int):
        # Legacy bridge ingest manifest (v1) — not v2.
        out["source_rows"] = int(raw["written"])
    return out
