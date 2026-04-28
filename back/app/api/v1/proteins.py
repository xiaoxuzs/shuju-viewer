"""某 cutoff 下的蛋白质列表与详情 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_cutoff, get_db
from app.models import Cutoff, Protein, Proteoform
from app.schemas import Page, ProteinDetailOut, ProteinListItemOut, ProteoformListItemOut

router = APIRouter(tags=["proteins"])

# 允许通过 query 参数 `sort` 排序的列名 → ORM 列映射；未命中时回退到 sequence_id。
SORT_MAP = {
    "sequence_id": Protein.sequence_id,
    "sequence_name": Protein.sequence_name,
    "compatible_proteoform_number": Protein.compatible_proteoform_number,
    "prsm_number": Protein.prsm_number,
    "best_prsm_e_value": Protein.best_prsm_e_value,
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteins",
    response_model=Page[ProteinListItemOut],
)
def list_proteins(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = Query(None, description="Search sequence_name / description."),
    sort: str = Query("sequence_id"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> Page[ProteinListItemOut]:
    """分页列出蛋白质；可选名称/描述模糊搜索。`total` 为过滤后总行数。"""
    stmt = select(Protein).where(Protein.cutoff_id == cutoff.id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Protein.sequence_name.ilike(like), Protein.sequence_description.ilike(like)))

    sort_col = SORT_MAP.get(sort, Protein.sequence_id)
    stmt = stmt.order_by(asc(sort_col) if order == "asc" else desc(sort_col))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return Page[ProteinListItemOut](
        items=[ProteinListItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}",
    response_model=ProteinDetailOut,
)
def get_protein(
    protein_id: int,
    session: Session = Depends(get_db),
    cutoff: Cutoff = Depends(get_cutoff),
) -> ProteinDetailOut:
    """单条蛋白质详情；路径中的 protein_id 为表 ``proteins.id``（主键）。"""
    protein = session.execute(
        select(Protein).where(Protein.cutoff_id == cutoff.id, Protein.id == protein_id)
    ).scalar_one_or_none()
    if protein is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "protein not found")

    pfs = (
        session.execute(
            select(Proteoform)
            .where(Proteoform.protein_id == protein.id)
            .order_by(Proteoform.proteoform_id)
        )
        .scalars()
        .all()
    )
    return ProteinDetailOut(
        id=protein.id,
        sequence_id=protein.sequence_id,
        sequence_name=protein.sequence_name,
        sequence_description=protein.sequence_description,
        compatible_proteoform_number=protein.compatible_proteoform_number,
        prsm_number=protein.prsm_number,
        best_prsm_id=protein.best_prsm_id,
        best_prsm_e_value=protein.best_prsm_e_value,
        proteoforms=[ProteoformListItemOut.model_validate(pf) for pf in pfs],
    )
