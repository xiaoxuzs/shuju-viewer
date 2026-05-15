"""LC-MS 3D map API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.lcms_map import LcmsMapRequest, build_lcms_map
from app.services import spectrum_memory_wiring
from app.spectrum_memory import CapacityError, NotResidentError


router = APIRouter(tags=["lcms"])


@router.get(
    "/datasets/{dataset_id}/runs/{run_id}/lcms-3d",
    response_model=dict[str, Any],
)
def lcms_3d_map(
    dataset_id: int,
    run_id: int,
    ms_level: int = Query(1, ge=1, le=2),
    center_scan: int | None = Query(None, ge=0),
    center_spec_id: int | None = Query(None, ge=0),
    center_rt_seconds: float | None = Query(None, ge=0),
    precursor_mz: float | None = Query(None, gt=0),
    rt_window_seconds: float = Query(240.0, gt=0, le=7200),
    mz_window: float | None = Query(80.0, gt=0, le=5000),
    frame_radius: int = Query(16, ge=0, le=200),
    rt_bins: int = Query(96, ge=8, le=512),
    mz_bins: int = Query(160, ge=8, le=1024),
    max_points: int = Query(45_000, ge=100, le=200_000),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    dataset = session.execute(
        text(
            """
            SELECT dataset_id, slug, source_root, capabilities, source_software
            FROM datasets
            WHERE dataset_id = :dataset_id
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().one_or_none()
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")

    source = _spectra_source(dataset)
    if source == "mzml_memory":
        try:
            spectrum_memory_wiring.ensure_mzml_dataset_resident(session, dataset_id)
        except CapacityError as exc:
            raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    elif source != "topfd_js":
        raise HTTPException(status.HTTP_409_CONFLICT, f"unsupported spectra_source for LC-MS map: {source}")

    request = LcmsMapRequest(
        dataset_id=dataset_id,
        run_id=run_id,
        source=source,
        slug=str(dataset.get("slug") or ""),
        source_root=dataset.get("source_root"),
        ms_level=ms_level,
        center_scan=center_scan,
        center_spec_id=center_spec_id,
        center_rt_seconds=center_rt_seconds,
        precursor_mz=precursor_mz,
        rt_window_seconds=rt_window_seconds,
        mz_window=mz_window,
        frame_radius=frame_radius,
        rt_bins=rt_bins,
        mz_bins=mz_bins,
        max_points=max_points,
    )
    try:
        return build_lcms_map(request)
    except NotResidentError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "mzML dataset is not resident in memory",
        ) from exc


def _spectra_source(dataset: Any) -> str:
    caps_raw = dataset.get("capabilities")
    caps = dict(caps_raw) if isinstance(caps_raw, dict) else {}
    source = caps.get("spectra_source")
    if source:
        return str(source)
    if str(dataset.get("source_software") or "").strip() == "TopPIC_prsm_js":
        return "mzml_memory"
    return "topfd_js"
