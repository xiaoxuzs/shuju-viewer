"""Import standalone mzML spectra into the universal schema."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.services.mzml_mapping import collect_mzml_files, normalize_spectrum_file_name

SOFTWARE = "mzML_only"


@dataclass
class MzmlOnlyImportStats:
    dataset_id: int
    run_id: int
    runs: int = 0
    proteins: int = 0
    peptides: int = 0
    proteoforms: int = 0
    matches: int = 0


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _is_uncompressed_mzml(path: Path) -> bool:
    return path.name.lower().endswith(".mzml")


def _under_viewer_derived(path: Path, root: Path) -> bool:
    try:
        return ".viewer-derived" in path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False


def _collect_viewable_mzml_files(root: Path, extra_roots: Sequence[Path] | None) -> list[Path]:
    files: dict[str, Path] = {}
    base = root.resolve()
    for path in collect_mzml_files(base):
        if _under_viewer_derived(path, base):
            continue
        if _is_uncompressed_mzml(path):
            files[str(path.resolve())] = path.resolve()
    for extra_root in extra_roots or ():
        for path in collect_mzml_files(extra_root):
            if _is_uncompressed_mzml(path):
                files[str(path.resolve())] = path.resolve()
    return sorted(files.values(), key=lambda item: str(item))


def _create_dataset(
    conn: Connection,
    *,
    root: Path,
    slug: str,
    name: str,
    analysis_shape: str,
    run_count: int,
) -> int:
    caps = {
        "spectra_source": "mzml_memory",
        "analysis_shape": analysis_shape,
        "import_mode": analysis_shape,
        "has_spectrum_files": True,
        "has_chromatogram": True,
        "has_identifications": False,
        "entity_types": [],
        "list_routes": [],
    }
    extra = {
        "import_stats": {
            "runs": run_count,
            "identification_rows": 0,
        }
    }
    row = conn.execute(
        text(
            """
            INSERT INTO datasets (
                dataset_name, slug, analysis_mode, source_software,
                source_root, status, description, capabilities, extra_metadata
            )
            VALUES (
                :name, :slug, 'TOP_DOWN', :software,
                :source_root, 'IMPORTED',
                'Standalone mzML spectra dataset imported for basic spectra viewing',
                CAST(:capabilities AS jsonb), CAST(:extra_metadata AS jsonb)
            )
            RETURNING dataset_id
            """
        ),
        {
            "name": name,
            "slug": slug,
            "software": SOFTWARE,
            "source_root": str(root),
            "capabilities": _json(caps),
            "extra_metadata": _json(extra),
        },
    ).one()
    return int(row.dataset_id)


def _insert_runs(
    conn: Connection,
    *,
    dataset_id: int,
    mzml_files: Sequence[Path],
    raw_conversion_by_mzml_key: dict[str, dict[str, Any]] | None,
) -> list[int]:
    raw_by_key = raw_conversion_by_mzml_key or {}
    run_ids: list[int] = []
    for mzml_path in mzml_files:
        key = normalize_spectrum_file_name(mzml_path.name)
        metadata: dict[str, Any] = {
            "raw_format": "mzml",
            "mzml_file_path": str(mzml_path),
        }
        raw_meta = raw_by_key.get(key)
        if raw_meta:
            raw_path = raw_meta.get("raw_path")
            raw_conversion = raw_meta.get("raw_conversion")
            if raw_path:
                metadata["raw_path"] = str(raw_path)
            if isinstance(raw_conversion, dict):
                metadata["raw_conversion"] = raw_conversion
        row = conn.execute(
            text(
                """
                INSERT INTO runs (
                    dataset_id, file_path, file_name,
                    analysis_mode, software, status, run_metadata
                )
                VALUES (
                    :dataset_id, :file_path, :file_name,
                    'TOP_DOWN', :software, 'IMPORTED', CAST(:run_metadata AS jsonb)
                )
                RETURNING run_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "file_path": str(mzml_path),
                "file_name": mzml_path.name,
                "software": SOFTWARE,
                "run_metadata": _json(metadata),
            },
        ).one()
        run_ids.append(int(row.run_id))
    return run_ids


def ingest_mzml_only(
    *,
    root: Path,
    database_url: str,
    slug: str,
    name: str,
    replace: bool = False,
    extra_mzml_roots: Sequence[Path] | None = None,
    raw_conversion_by_mzml_key: dict[str, dict[str, Any]] | None = None,
) -> MzmlOnlyImportStats:
    """Create a spectra-only dataset with one run per mzML file."""
    resolved_root = root.resolve()
    mzml_files = _collect_viewable_mzml_files(resolved_root, extra_mzml_roots)
    if not mzml_files:
        raise ValueError(f"no uncompressed mzML files found under {resolved_root}")

    raw_by_key = raw_conversion_by_mzml_key or {}
    has_raw_source = any(normalize_spectrum_file_name(path.name) in raw_by_key for path in mzml_files)
    analysis_shape = "raw_mzml_only" if has_raw_source else "mzml_only"

    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        if replace:
            conn.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": slug})
        dataset_id = _create_dataset(
            conn,
            root=resolved_root,
            slug=slug,
            name=name,
            analysis_shape=analysis_shape,
            run_count=len(mzml_files),
        )
        run_ids = _insert_runs(
            conn,
            dataset_id=dataset_id,
            mzml_files=mzml_files,
            raw_conversion_by_mzml_key=raw_by_key,
        )
        conn.execute(text("UPDATE datasets SET status = 'READY' WHERE dataset_id = :dataset_id"), {"dataset_id": dataset_id})
        conn.execute(text("UPDATE runs SET status = 'READY' WHERE dataset_id = :dataset_id"), {"dataset_id": dataset_id})

    return MzmlOnlyImportStats(
        dataset_id=dataset_id,
        run_id=run_ids[0],
        runs=len(run_ids),
    )
