"""Bottom-Up match summary endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import lists_service
from app.schemas import BuMatchDetailOut

router = APIRouter()


@router.get("/datasets/{slug}/matches/{match_id}", response_model=BuMatchDetailOut)
def match_detail(slug: str, match_id: int, session: Session = Depends(get_db)) -> BuMatchDetailOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return lists_service.get_match_detail(session, dataset, match)


@router.get("/datasets/{slug}/matches/{match_id}/xic")
def match_xic(slug: str, match_id: int, session: Session = Depends(get_db)) -> None:
    dataset = require_bu_dataset(session, slug)
    require_bu_match(session, int(dataset["dataset_id"]), match_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")


@router.get("/datasets/{slug}/matches/{match_id}/spectrum/ms2")
def match_ms2(slug: str, match_id: int, session: Session = Depends(get_db)) -> None:
    dataset = require_bu_dataset(session, slug)
    require_bu_match(session, int(dataset["dataset_id"]), match_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")


@router.get("/datasets/{slug}/matches/{match_id}/spectrum/ms1")
def match_ms1(slug: str, match_id: int, session: Session = Depends(get_db)) -> None:
    dataset = require_bu_dataset(session, slug)
    require_bu_match(session, int(dataset["dataset_id"]), match_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")

