"""某 cutoff 下的 proteoform 列表与详情 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_cutoff, get_db
from app.models import Cutoff, Proteoform, Prsm
from app.schemas import Page, PrsmListItemOut, ProteoformDetailOut, ProteoformListItemOut

router = APIRouter(tags=["proteoforms"])

# 允许 `sort` 的列；未命中时回退到 proteoform_id。
SORT_MAP = {
    "proteoform_id": Proteoform.proteoform_id,
    "prsm_number": Proteoform.prsm_number,
    "best_prsm_e_value": Proteoform.best_prsm_e_value,
    "proteoform_mass": Proteoform.proteoform_mass,
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteoforms",
    response_model=Page[ProteoformListItemOut],
)
def list_proteoforms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    protein_id: int | None = Query(None),
    sort: str = Query("proteoform_id"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> Page[ProteoformListItemOut]:
    """分页列出 proteoform；若传 ``protein_id`` 则仅返回该蛋白质（表主键）下的形式。"""
    stmt = select(Proteoform).where(Proteoform.cutoff_id == cutoff.id)
    if protein_id is not None:
        stmt = stmt.where(Proteoform.protein_id == protein_id)

    sort_col = SORT_MAP.get(sort, Proteoform.proteoform_id)
    stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return Page[ProteoformListItemOut](
        items=[ProteoformListItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}",
    response_model=ProteoformDetailOut,
)
def get_proteoform(
    proteoform_id: int,
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> ProteoformDetailOut:
    """详情路径中的 proteoform_id 为 ``proteoforms.id``（主键），非 TopPIC 的 proteoform 业务号。"""
    pf = session.execute(
        select(Proteoform).where(Proteoform.cutoff_id == cutoff.id, Proteoform.id == proteoform_id)
    ).scalar_one_or_none()
    if pf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proteoform not found")

    prsms = (
        session.execute(
            select(Prsm).where(Prsm.proteoform_id == pf.id).order_by(Prsm.e_value.asc().nulls_last())
        )
        .scalars()
        .all()
    )
    return ProteoformDetailOut(
        id=pf.id,
        protein_id=pf.protein_id,
        proteoform_id=pf.proteoform_id,
        sequence_id=pf.sequence_id,
        sequence_name=pf.sequence_name,
        proteoform_mass=pf.proteoform_mass,
        prsm_number=pf.prsm_number,
        best_prsm_id=pf.best_prsm_id,
        best_prsm_e_value=pf.best_prsm_e_value,
        n_acetylation=pf.n_acetylation,
        unexpected_shift_number=pf.unexpected_shift_number,
        prsms=[PrsmListItemOut.model_validate(p) for p in prsms],
    )
