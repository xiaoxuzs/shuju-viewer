"""数据集与 cutoff 元数据 API：列表、详情及每个 cutoff 下实体计数。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_dataset
from app.models import Cutoff, Dataset, Protein, Proteoform, Prsm
from app.schemas import CutoffOut, DatasetOut

router = APIRouter(tags=["datasets"])


def _cutoffs_payload(session: Session, dataset_id: int) -> list[CutoffOut]:
    """查询某数据集下所有 cutoff，并分别统计蛋白质 / proteoform / PrSM 行数。"""
    cutoffs = (
        session.execute(select(Cutoff).where(Cutoff.dataset_id == dataset_id).order_by(Cutoff.id))
        .scalars()
        .all()
    )
    items: list[CutoffOut] = []
    for c in cutoffs:
        protein_count = session.scalar(select(func.count()).select_from(Protein).where(Protein.cutoff_id == c.id)) or 0
        proteoform_count = (
            session.scalar(select(func.count()).select_from(Proteoform).where(Proteoform.cutoff_id == c.id)) or 0
        )
        prsm_count = session.scalar(select(func.count()).select_from(Prsm).where(Prsm.cutoff_id == c.id)) or 0
        items.append(
            CutoffOut(
                id=c.id,
                kind=c.kind,
                label=c.label,
                protein_count=protein_count,
                proteoform_count=proteoform_count,
                prsm_count=prsm_count,
            )
        )
    return items


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_db)) -> list[DatasetOut]:
    """返回全部数据集，按 id 排序；每个元素附带嵌套的 cutoff 统计。"""
    datasets = session.execute(select(Dataset).order_by(Dataset.id)).scalars().all()
    return [
        DatasetOut(
            id=d.id,
            slug=d.slug,
            name=d.name,
            description=d.description,
            source_path=d.source_path,
            created_at=d.created_at,
            updated_at=d.updated_at,
            cutoffs=_cutoffs_payload(session, d.id),
        )
        for d in datasets
    ]


@router.get("/datasets/{slug}", response_model=DatasetOut)
def get_dataset_detail(
    session: Session = Depends(get_db),
    dataset: Dataset = Depends(get_dataset),
) -> DatasetOut:
    """按 slug 取单个数据集；slug 不存在时由依赖注入层返回 404。"""
    return DatasetOut(
        id=dataset.id,
        slug=dataset.slug,
        name=dataset.name,
        description=dataset.description,
        source_path=dataset.source_path,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        cutoffs=_cutoffs_payload(session, dataset.id),
    )
