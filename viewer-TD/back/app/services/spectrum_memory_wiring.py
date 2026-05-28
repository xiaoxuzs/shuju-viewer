"""DB → :class:`MzmlBundleSpec` and ``ensure_dataset_resident`` (keeps ORM/SQL out of spectrum_memory)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.incoming_path_relocate import try_fix_stale_incoming_absolute_path
from app.services.mzml_mapping import build_mapping_from_extracted_dataset, normalize_spectrum_file_name
from app.spectrum_memory import MzmlBundleSpec, MzmlRunFileSpec, ensure_dataset_resident


def _capabilities_effective(raw: Any, *, source_software: str | None) -> dict[str, Any]:
    caps: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if caps.get("spectra_source") is None and (source_software or "").strip() == "TopPIC_prsm_js":
        caps = {**caps, "spectra_source": "mzml_memory"}
    return caps


def _is_mzml_memory_dataset(caps: dict[str, Any]) -> bool:
    return caps.get("spectra_source") in {"mzml_memory", "mixed"}


def _resolve_path_on_disk(raw_path: Path) -> Path | None:
    fixed = try_fix_stale_incoming_absolute_path(raw_path)
    candidate = fixed if fixed is not None else raw_path
    try:
        if candidate.is_file():
            return candidate.resolve()
    except OSError:
        return None
    return None


def build_mzml_bundle_spec(session: Session, dataset_id: int) -> MzmlBundleSpec | None:
    """Return None if this dataset does not use mzML-backed spectra."""
    ds = session.execute(
        text(
            """
            SELECT dataset_id, source_root, capabilities, source_software
            FROM datasets
            WHERE dataset_id = :dataset_id
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().one_or_none()
    if ds is None:
        return None
    caps = _capabilities_effective(ds.get("capabilities"), source_software=ds.get("source_software"))
    if not _is_mzml_memory_dataset(caps):
        return None
    is_mixed = caps.get("spectra_source") == "mixed"

    rows = session.execute(
        text(
            """
            SELECT r.run_id, r.file_name, r.run_metadata
            FROM runs r
            WHERE r.dataset_id = :dataset_id
              AND EXISTS (
                  SELECT 1 FROM identification_matches im
                  WHERE im.dataset_id = r.dataset_id AND im.run_id = r.run_id
              )
              AND (
                  CAST(:is_mixed AS boolean) = false
                  OR jsonb_extract_path_text(r.run_metadata, 'raw_format') = 'mzml'
              )
            ORDER BY r.run_id
            """
        ),
        {"dataset_id": dataset_id, "is_mixed": is_mixed},
    ).mappings().all()

    source_root = Path(str(ds.get("source_root") or "")).resolve()
    mapping: dict[str, Path] | None = None

    def mapping_lookup(file_name: str) -> Path:
        nonlocal mapping
        if mapping is None:
            mapping = build_mapping_from_extracted_dataset(ingest_root=source_root).mapping
        key = normalize_spectrum_file_name(file_name)
        hit = mapping.get(key)
        if hit is None:
            raise RuntimeError(f"cannot map run.file_name to mzML: {file_name!r}")
        return hit.resolve()

    run_specs: list[MzmlRunFileSpec] = []
    for row in rows:
        run_id = int(row["run_id"])
        file_name = str(row.get("file_name") or "")
        meta = row.get("run_metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        path: Path | None = None
        mzml_raw = meta.get("mzml_file_path")
        if mzml_raw:
            path = _resolve_path_on_disk(Path(str(mzml_raw)))

        if path is None:
            path = mapping_lookup(file_name)
            session.execute(
                text(
                    "UPDATE runs SET run_metadata = run_metadata || CAST(:patch AS jsonb) "
                    "WHERE run_id = :run_id"
                ),
                {
                    "run_id": run_id,
                    "patch": json.dumps({"mzml_file_path": str(path)}, ensure_ascii=False),
                },
            )
            if not is_mixed:
                session.execute(
                    text(
                        "UPDATE datasets SET capabilities = capabilities || CAST(:cap_patch AS jsonb) "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id, "cap_patch": '{"spectra_source": "mzml_memory"}'},
                )
        else:
            if mzml_raw:
                try:
                    raw_declared = Path(str(mzml_raw))
                    raw_resolved = raw_declared.resolve()
                except OSError:
                    raw_resolved = None
                if raw_resolved is not None and path != raw_resolved:
                    session.execute(
                        text(
                            "UPDATE runs SET run_metadata = run_metadata || CAST(:patch AS jsonb) "
                            "WHERE run_id = :run_id"
                        ),
                        {
                            "run_id": run_id,
                            "patch": json.dumps({"mzml_file_path": str(path)}, ensure_ascii=False),
                        },
                    )

        if not path.is_file():
            raise RuntimeError(f"mzML file missing for run_id={run_id}: {path}")

        run_specs.append(MzmlRunFileSpec(run_id=run_id, mzml_path=path))

    return MzmlBundleSpec(dataset_id=dataset_id, runs=tuple(run_specs))


def ensure_mzml_dataset_resident(session: Session, dataset_id: int) -> None:
    """Load all mzML for this dataset into the global pool (no-op if not mzml_memory)."""
    spec = build_mzml_bundle_spec(session, dataset_id)
    if spec is None:
        return
    ensure_dataset_resident(spec)
    session.commit()
