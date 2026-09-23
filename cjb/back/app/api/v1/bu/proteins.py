"""Bottom-Up protein detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services.protein_detail_service import get_protein_detail
from app.schemas import BuProteinDetailOut

router = APIRouter()


@router.get("/datasets/{slug}/proteins/{protein_id}", response_model=BuProteinDetailOut)
def protein_detail(slug: str, protein_id: int, session: Session = Depends(get_db)) -> BuProteinDetailOut:
    dataset = require_bu_dataset(session, slug)
    detail = get_protein_detail(session, dataset, protein_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="protein_not_found")
    return detail

