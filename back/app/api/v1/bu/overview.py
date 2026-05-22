"""Bottom-Up dataset overview endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services.overview_service import get_overview
from app.schemas import BuOverviewOut

router = APIRouter()


@router.get("/datasets/{slug}/overview", response_model=BuOverviewOut)
def overview(slug: str, session: Session = Depends(get_db)) -> BuOverviewOut:
    dataset = require_bu_dataset(session, slug)
    return get_overview(session, dataset)


@router.get("/datasets/{slug}/overview/rt-mz")
def rt_mz(slug: str, session: Session = Depends(get_db)) -> None:
    require_bu_dataset(session, slug)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")

