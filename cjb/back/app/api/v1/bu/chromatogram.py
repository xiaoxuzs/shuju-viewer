"""Bottom-Up chromatogram and DIA window placeholders."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services import chromatogram_service
from app.schemas import BuChromatogramOut, BuDiaWindowsOut

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


@router.get("/datasets/{slug}/runs/{run_id}/dia-windows", response_model=BuDiaWindowsOut)
def dia_windows(slug: str, run_id: int, session: Session = Depends(get_db)) -> BuDiaWindowsOut:
    dataset = require_bu_dataset(session, slug)
    return chromatogram_service.get_dia_windows(session, dataset, run_id)
