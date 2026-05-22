"""Bottom-Up protein detail endpoint placeholder."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset

router = APIRouter()


@router.get("/datasets/{slug}/proteins/{protein_id}")
def protein_detail(slug: str, protein_id: int, session: Session = Depends(get_db)) -> None:
    require_bu_dataset(session, slug)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")

