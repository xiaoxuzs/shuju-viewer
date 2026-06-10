"""Dynamic spectra API backed by in-memory mzML (``app.spectrum_memory``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.incoming_path_relocate import try_fix_stale_incoming_absolute_path
from app.services import spectrum_memory_wiring
from app.services.mzml_mapping import (
    build_mapping_from_extracted_dataset,
    normalize_spectrum_file_name,
)
from app.spectrum_memory import CapacityError, NotResidentError, get_mzml_spectrum, release_dataset


router = APIRouter(tags=["mzml-spectra"])


@router.get(
    "/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}",
    response_model=dict[str, Any],
)
def mzml_spectrum(
    dataset_id: int,
    run_id: int,
    scan_number: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    # Resolve mzML path from strict run mapping.
    row = session.execute(
        text(
            """
            SELECT run_id, dataset_id, file_name, run_metadata
            FROM runs
            WHERE run_id = :run_id AND dataset_id = :dataset_id
            """
        ),
        {"run_id": run_id, "dataset_id": dataset_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")

    run_metadata = row.get("run_metadata") or {}
    mzml_path = run_metadata.get("mzml_file_path")
    path_committed = False
    if not mzml_path:
        # Backfill mapping for older imports (or interrupted finalize):
        # derive mapping from datasets.source_root on disk.
        ds = session.execute(
            text("SELECT source_root, capabilities FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).mappings().one_or_none()
        if ds is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
        source_root = Path(str(ds.get("source_root") or "")).resolve()
        try:
            mapping = build_mapping_from_extracted_dataset(ingest_root=source_root).mapping
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status.HTTP_409_CONFLICT, f"cannot derive mzML mapping: {exc}") from exc
        file_name = str(row.get("file_name") or "")
        key = normalize_spectrum_file_name(file_name)
        mzml = mapping.get(key)
        if mzml is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"cannot map run.file_name to mzML: {file_name}",
            )
        mzml_path = str(mzml)
        # Persist run mapping for future requests.
        session.execute(
            text(
                "UPDATE runs SET run_metadata = run_metadata || CAST(:patch AS jsonb) "
                "WHERE run_id = :run_id"
            ),
            {"run_id": run_id, "patch": json.dumps({"mzml_file_path": mzml_path}, ensure_ascii=False)},
        )
        # Also ensure dataset advertises mzml_memory for frontend routing.
        session.execute(
            text(
                "UPDATE datasets SET capabilities = capabilities || CAST(:cap_patch AS jsonb) "
                "WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id, "cap_patch": '{"spectra_source": "mzml_memory"}'},
        )
        # get_db() does not auto-commit; persist backfill or the next request still sees old rows.
        session.commit()
        path_committed = True

    raw_path = Path(str(mzml_path))
    missing_before = not raw_path.is_file()
    path = try_fix_stale_incoming_absolute_path(raw_path)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"mzML not found: {mzml_path}")
    if missing_before and str(path) != str(mzml_path):
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
        session.commit()
        path_committed = True

    if path_committed:
        release_dataset(dataset_id)

    try:
        spectrum_memory_wiring.ensure_mzml_dataset_resident(session, dataset_id)
    except CapacityError as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    try:
        spec = get_mzml_spectrum(dataset_id, run_id, scan_number)
    except NotResidentError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "谱图内存未加载：请先在数据集列表中打开该数据集以预载 mzML。",
        ) from exc
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scan not found in mzML: {scan_number}")

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        **spec,
    }
