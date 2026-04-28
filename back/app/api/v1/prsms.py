"""某 cutoff 下的 PrSM 列表与详情 API；详情按业务 ``prsm_id`` 查询（见 ``get_prsm`` 文档）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_cutoff, get_db
from app.models import Cutoff, Prsm
from app.schemas import Page, PrsmDetailOut, PrsmListItemOut

router = APIRouter(tags=["prsms"])

# 列表接口允许的 ``sort`` 字段；未命中时默认按 e_value。
SORT_MAP = {
    "prsm_id": Prsm.prsm_id,
    "e_value": Prsm.e_value,
    "p_value": Prsm.p_value,
    "precursor_mono_mass": Prsm.precursor_mono_mass,
    "precursor_charge": Prsm.precursor_charge,
    "matched_fragment_number": Prsm.matched_fragment_number,
    "matched_peak_number": Prsm.matched_peak_number,
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/prsms",
    response_model=Page[PrsmListItemOut],
)
def list_prsms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    proteoform_id: int | None = Query(None, description="Filter by proteoform.id"),
    protein_id: int | None = Query(None),
    sort: str = Query("e_value"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> Page[PrsmListItemOut]:
    stmt = select(Prsm).where(Prsm.cutoff_id == cutoff.id)
    if proteoform_id is not None:
        stmt = stmt.where(Prsm.proteoform_id == proteoform_id)
    if protein_id is not None:
        from app.models import Proteoform

        stmt = stmt.join(Proteoform, Proteoform.id == Prsm.proteoform_id).where(
            Proteoform.protein_id == protein_id
        )

    sort_col = SORT_MAP.get(sort, Prsm.e_value)
    stmt = stmt.order_by(
        asc(sort_col).nulls_last() if order == "asc" else desc(sort_col).nulls_last()
    )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return Page[PrsmListItemOut](
        items=[PrsmListItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}",
    response_model=PrsmDetailOut,
)
def get_prsm(
    prsm_id: int,
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> PrsmDetailOut:
    """Look up a PrSM by its **business** ``prsm_id`` inside the given cutoff.

    The composite ``(cutoff_id, prsm_id)`` is unique (see
    :class:`app.models.protein.Prsm` ``__table_args__``). Using the business id
    here means the URL shown in the UI (``PrSM #4534``) matches the navigation
    URL (``/prsms/4534``), and it allows links coming from
    ``Protein.best_prsm_id`` / ``Proteoform.best_prsm_id`` (which store the
    business id, not the DB primary key) to resolve correctly.
    """
    row = session.execute(
        select(Prsm).where(Prsm.cutoff_id == cutoff.id, Prsm.prsm_id == prsm_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prsm not found")
    return PrsmDetailOut.model_validate(row)
