"""Dataset and cutoff metadata API backed by the universal schema."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import cutoff_id, cutoff_label, require_dataset
from app.schemas import CutoffOut, DatasetDeletedOut, DatasetOut
from app.services import import_jobs, spectrum_memory_wiring
from app.spectrum_memory import CapacityError

router = APIRouter(tags=["datasets"])


def _capabilities_out(raw: Any, *, source_software: str | None) -> dict[str, Any]:
    """Normalize JSONB + infer ``spectra_source`` for legacy prsm*.js-only rows."""
    caps: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if caps.get("spectra_source") is None and (source_software or "").strip() == "TopPIC_prsm_js":
        caps = {**caps, "spectra_source": "mzml_memory"}
    return caps


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _cutoffs_payload(session: Session, dataset_id: int) -> list[CutoffOut]:
    """Synthesize legacy cutoffs from ``identification_matches.source_cutoff``."""
    rows = session.execute(
        text(
            """
            WITH cutoff_matches AS (
                SELECT
                    jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') AS cutoff,
                    im.entity_type,
                    im.entity_id
                FROM identification_matches im
                WHERE im.dataset_id = :dataset_id
            )
            SELECT
                cm.cutoff AS cutoff,
                count(*) AS prsm_count,
                count(DISTINCT cm.entity_id) FILTER (WHERE cm.entity_type = 'PROTEOFORM')
                    AS proteoform_count,
                count(DISTINCT prm.protein_id)
                    AS protein_count
            FROM cutoff_matches cm
            LEFT JOIN protein_relation_mapping prm
              ON prm.dataset_id = :dataset_id
             AND prm.entity_type = cm.entity_type
             AND prm.entity_id = cm.entity_id
            WHERE cm.cutoff IS NOT NULL
            GROUP BY cm.cutoff
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()

    by_cutoff = {row["cutoff"]: row for row in rows}
    return [
        CutoffOut(
            id=cutoff_id(kind),
            kind=kind,
            label=cutoff_label(kind),
            protein_count=int(by_cutoff.get(kind, {}).get("protein_count") or 0),
            proteoform_count=int(by_cutoff.get(kind, {}).get("proteoform_count") or 0),
            prsm_count=int(by_cutoff.get(kind, {}).get("prsm_count") or 0),
        )
        for kind in ("prsm", "proteoform")
    ]


def _dataset_out(*, row: Any, cutoffs: list[CutoffOut]) -> DatasetOut:
    return DatasetOut(
        id=row["dataset_id"],
        slug=row["slug"],
        name=row["dataset_name"],
        description=row["description"],
        source_path=row["source_root"],
        capabilities=_capabilities_out(row.get("capabilities"), source_software=row.get("source_software")),
        analysis_mode=row.get("analysis_mode"),
        status=row.get("status"),
        source_software=row.get("source_software"),
        extra_metadata=_json_object(row.get("extra_metadata")),
        created_at=row["created_at"],
        updated_at=None,
        cutoffs=cutoffs,
    )


def _ensure_dataset_spectra_resident(session: Session, dataset: dict[str, Any]) -> None:
    """Trigger mzML residency for mzML-backed datasets."""
    spectrum_memory_wiring.ensure_mzml_dataset_resident(session, int(dataset["dataset_id"]))


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_db)) -> list[DatasetOut]:
    """List all datasets ordered by id with cutoff statistics."""
    datasets = session.execute(
        text(
            """
            SELECT
                dataset_id, slug, dataset_name, description,
                analysis_mode, status, source_software, source_root,
                created_at, capabilities, extra_metadata
            FROM datasets
            ORDER BY dataset_id
            """
        )
    ).mappings().all()
    return [
        _dataset_out(
            row=d,
            cutoffs=_cutoffs_payload(session, d["dataset_id"]),
        )
        for d in datasets
    ]


@router.get("/datasets/{slug}", response_model=DatasetOut)
def get_dataset_detail(
    slug: str,
    session: Session = Depends(get_db),
) -> DatasetOut:
    """Return one dataset by slug; 404 when missing."""
    dataset = require_dataset(session, slug)
    try:
        _ensure_dataset_spectra_resident(session, dataset)
    except CapacityError as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    dataset_id = int(dataset["dataset_id"])
    return _dataset_out(
        row=dataset,
        cutoffs=_cutoffs_payload(session, dataset_id),
    )


@router.delete("/datasets/{slug}", response_model=DatasetDeletedOut)
def delete_dataset(slug: str) -> DatasetDeletedOut:
    """Delete a dataset from the database (disk files are not removed)."""
    try:
        result = import_jobs.delete_dataset(slug)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset not found: {slug}") from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return DatasetDeletedOut(
        slug=slug,
        deleted_db=result.deleted_db,
        deleted_disk=result.deleted_disk,
        folder=result.folder,
        folder_existed=result.folder_existed,
    )
