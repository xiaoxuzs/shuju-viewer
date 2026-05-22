"""Bottom-Up list endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services import lists_service
from app.schemas import BuMatchListItemOut, BuPeptideDetailOut, BuPeptideListItemOut, BuProteinListItemOut, Page

router = APIRouter()


@router.get("/datasets/{slug}/proteins", response_model=Page[BuProteinListItemOut])
def proteins(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    decoy: bool = False,
    session: Session = Depends(get_db),
) -> Page[BuProteinListItemOut]:
    dataset = require_bu_dataset(session, slug)
    return lists_service.list_proteins(
        session,
        dataset,
        page=page,
        page_size=page_size,
        search=search,
        decoy=decoy,
    )


@router.get("/datasets/{slug}/peptides", response_model=Page[BuPeptideListItemOut])
def peptides(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    q_max: float | None = None,
    session: Session = Depends(get_db),
) -> Page[BuPeptideListItemOut]:
    dataset = require_bu_dataset(session, slug)
    return lists_service.list_peptides(
        session,
        dataset,
        page=page,
        page_size=page_size,
        search=search,
        q_max=q_max,
    )


@router.get("/datasets/{slug}/peptides/{peptide_id}", response_model=BuPeptideDetailOut)
def peptide_detail(
    slug: str,
    peptide_id: int,
    session: Session = Depends(get_db),
) -> BuPeptideDetailOut:
    dataset = require_bu_dataset(session, slug)
    detail = lists_service.get_peptide_detail(session, dataset, peptide_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="peptide_not_found")
    return detail


@router.get("/datasets/{slug}/matches", response_model=Page[BuMatchListItemOut])
def matches(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    q_max: float | None = None,
    run_id: int | None = None,
    peptide_id: int | None = None,
    protein_id: int | None = None,
    charge: int | None = None,
    search: str | None = None,
    decoy: bool = False,
    sort: str = "q_value",
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
) -> Page[BuMatchListItemOut]:
    dataset = require_bu_dataset(session, slug)
    return lists_service.list_matches(
        session,
        dataset,
        page=page,
        page_size=page_size,
        q_max=q_max,
        run_id=run_id,
        peptide_id=peptide_id,
        protein_id=protein_id,
        charge=charge,
        search=search,
        decoy=decoy,
        sort=sort,
        order=order,
    )

