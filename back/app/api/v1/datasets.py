"""数据集与 cutoff 元数据 API：兼容旧前端输出，读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import cutoff_id, cutoff_label, require_dataset
from app.schemas import CutoffOut, DatasetOut

router = APIRouter(tags=["datasets"])


def _cutoffs_payload(session: Session, dataset_id: int) -> list[CutoffOut]:
    """Synthesize legacy cutoffs from universal match source_cutoff metadata."""
    protein_count = session.scalar(
        text("SELECT count(1) FROM proteins WHERE dataset_id = :dataset_id"),
        {"dataset_id": dataset_id},
    ) or 0
    proteoform_count = session.scalar(
        text("SELECT count(1) FROM proteoforms WHERE dataset_id = :dataset_id"),
        {"dataset_id": dataset_id},
    ) or 0
    prsm_counts = dict(
        session.execute(
            text(
                """
                SELECT jsonb_extract_path_text(extra_metadata, 'source_cutoff') AS cutoff, count(1)
                FROM identification_matches
                WHERE dataset_id = :dataset_id
                GROUP BY cutoff
                """
            ),
            {"dataset_id": dataset_id},
        ).all()
    )
    return [
        CutoffOut(
            id=cutoff_id(kind),
            kind=kind,
            label=cutoff_label(kind),
            protein_count=protein_count,
            proteoform_count=proteoform_count,
            prsm_count=prsm_counts.get(kind, 0),
        )
        for kind in ("prsm", "proteoform")
    ]


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_db)) -> list[DatasetOut]:
    """返回全部数据集，按 id 排序；每个元素附带嵌套的 cutoff 统计。"""
    datasets = session.execute(
        text(
            """
            SELECT dataset_id, slug, dataset_name, description, source_root, created_at
            FROM datasets
            ORDER BY dataset_id
            """
        )
    ).mappings().all()
    return [
        DatasetOut(
            id=d["dataset_id"],
            slug=d["slug"],
            name=d["dataset_name"],
            description=d["description"],
            source_path=d["source_root"],
            created_at=d["created_at"],
            updated_at=d["created_at"],
            cutoffs=_cutoffs_payload(session, d["dataset_id"]),
        )
        for d in datasets
    ]


@router.get("/datasets/{slug}", response_model=DatasetOut)
def get_dataset_detail(
    slug: str,
    session: Session = Depends(get_db),
) -> DatasetOut:
    """按 slug 取单个数据集；slug 不存在时由依赖注入层返回 404。"""
    dataset = require_dataset(session, slug)
    return DatasetOut(
        id=dataset["dataset_id"],
        slug=dataset["slug"],
        name=dataset["dataset_name"],
        description=dataset["description"],
        source_path=dataset["source_root"],
        created_at=dataset["created_at"],
        updated_at=dataset["created_at"],
        cutoffs=_cutoffs_payload(session, dataset["dataset_id"]),
    )
