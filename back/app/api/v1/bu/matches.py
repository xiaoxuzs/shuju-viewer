"""Bottom-Up match summary endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import lists_service, mobility_service, spectrum_facade, xic_service
from app.schemas import BuMatchDetailOut, BuMobilitySliceOut, BuSpectrumV1, BuXicOut

router = APIRouter()


@router.get("/datasets/{slug}/matches/{match_id}", response_model=BuMatchDetailOut)
def match_detail(slug: str, match_id: int, session: Session = Depends(get_db)) -> BuMatchDetailOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return lists_service.get_match_detail(session, dataset, match)


@router.get("/datasets/{slug}/matches/{match_id}/xic", response_model=BuXicOut)
def match_xic(slug: str, match_id: int, ppm: float = 10.0, session: Session = Depends(get_db)) -> BuXicOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return xic_service.get_match_xic(session, dataset, match, ppm=ppm)


@router.get("/datasets/{slug}/matches/{match_id}/spectrum/ms2", response_model=BuSpectrumV1)
def match_ms2(slug: str, match_id: int, ppm: float = 20.0, session: Session = Depends(get_db)) -> BuSpectrumV1:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return spectrum_facade.get_match_ms2(session, dataset, match, ppm=ppm)


@router.get("/datasets/{slug}/matches/{match_id}/spectrum/ms1", response_model=BuSpectrumV1)
def match_ms1(slug: str, match_id: int, session: Session = Depends(get_db)) -> BuSpectrumV1:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return spectrum_facade.get_match_ms1(session, dataset, match)


@router.get("/datasets/{slug}/matches/{match_id}/mobility-slice", response_model=BuMobilitySliceOut)
def match_mobility_slice(slug: str, match_id: int, session: Session = Depends(get_db)) -> BuMobilitySliceOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return mobility_service.get_match_mobility_slice(dataset, match)
