"""Bottom-Up PFMB MS2 annotation endpoints (pre-computed sidecar layer)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import ms2_annotation_svc
from app.schemas import BuMs2AnnotationMatrixOut, BuMs2AnnotationOut, BuMs2SlotListOut

router = APIRouter()


@router.get("/datasets/{slug}/matches/{match_id}/ms2-slots", response_model=BuMs2SlotListOut)
def match_ms2_slots(slug: str, match_id: int, session: Session = Depends(get_db)) -> BuMs2SlotListOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return ms2_annotation_svc.get_slots(dataset, match)


@router.get(
    "/datasets/{slug}/matches/{match_id}/ms2-annotation/{prsm_index}",
    response_model=BuMs2AnnotationOut,
)
def match_ms2_annotation(
    slug: str,
    match_id: int,
    prsm_index: int,
    session: Session = Depends(get_db),
) -> BuMs2AnnotationOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return ms2_annotation_svc.get_annotation(dataset, match, prsm_index)


@router.get(
    "/datasets/{slug}/matches/{match_id}/ms2-annotation-matrix",
    response_model=BuMs2AnnotationMatrixOut,
)
def match_ms2_annotation_matrix(
    slug: str,
    match_id: int,
    session: Session = Depends(get_db),
) -> BuMs2AnnotationMatrixOut:
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, int(dataset["dataset_id"]), match_id)
    return ms2_annotation_svc.get_annotation_matrix(dataset, match)
