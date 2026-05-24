"""Bottom-Up chromatogram and DIA window placeholders."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services import chromatogram_service
from app.schemas import BuChromatogramOut

router = APIRouter()


@router.get("/datasets/{slug}/runs/{run_id}/chromatogram", response_model=BuChromatogramOut)
def chromatogram(
    slug: str,
    run_id: int,
    type: Literal["tic", "bpc"] = "tic",
    session: Session = Depends(get_db),
) -> BuChromatogramOut:
    dataset = require_bu_dataset(session, slug)
    return chromatogram_service.get_chromatogram(session, dataset, run_id, chrom_type=type)


@router.get("/datasets/{slug}/runs/{run_id}/dia-windows")
def dia_windows(slug: str, run_id: int, session: Session = Depends(get_db)) -> None:
    require_bu_dataset(session, slug)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")
