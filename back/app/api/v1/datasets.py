"""数据集与 cutoff 元数据 API：兼容旧前端输出，读取 universal schema。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import cutoff_id, cutoff_label, require_dataset
from app.schemas import CutoffOut, DatasetDeletedOut, DatasetOut
from app.services import import_jobs

router = APIRouter(tags=["datasets"])


def _capabilities_out(raw: Any, *, source_software: str | None) -> dict[str, Any]:
    """Normalize JSONB + infer ``spectra_source`` for legacy prsm*.js-only rows."""
    caps: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if caps.get("spectra_source") is None and (source_software or "").strip() == "TopPIC_prsm_js":
        caps = {**caps, "spectra_source": "mzml_memory"}
    return caps


def _cutoffs_payload(session: Session, dataset_id: int) -> list[CutoffOut]:
    """Synthesize legacy cutoffs from ``identification_matches.source_cutoff``.

    All three counts are filtered by ``extra_metadata.source_cutoff`` so the
    two virtual cutoffs (``prsm`` / ``proteoform``) get distinct numbers, even
    though proteins and proteoforms are stored as cutoff-independent rows in
    the universal schema.
    """
    rows = session.execute(
        text(
            """
            WITH cutoff_matches AS (
                SELECT
                    jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') AS cutoff,
                    im.entity_type,
                    im.entity_id
                FROM identification_matches im
                WHERE im.dataset_id = :dataset_id
            )
            SELECT
                cm.cutoff AS cutoff,
                count(*) AS prsm_count,
                count(DISTINCT cm.entity_id) FILTER (WHERE cm.entity_type = 'PROTEOFORM')
                    AS proteoform_count,
                count(DISTINCT prm.protein_id)
                    AS protein_count
            FROM cutoff_matches cm
            LEFT JOIN protein_relation_mapping prm
              ON prm.dataset_id = :dataset_id
             AND prm.entity_type = cm.entity_type
             AND prm.entity_id = cm.entity_id
            WHERE cm.cutoff IS NOT NULL
            GROUP BY cm.cutoff
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()

    by_cutoff = {row["cutoff"]: row for row in rows}
    return [
        CutoffOut(
            id=cutoff_id(kind),
            kind=kind,
            label=cutoff_label(kind),
            protein_count=int(by_cutoff.get(kind, {}).get("protein_count") or 0),
            proteoform_count=int(by_cutoff.get(kind, {}).get("proteoform_count") or 0),
            prsm_count=int(by_cutoff.get(kind, {}).get("prsm_count") or 0),
        )
        for kind in ("prsm", "proteoform")
    ]


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_db)) -> list[DatasetOut]:
    """返回全部数据集，按 id 排序；每个元素附带嵌套的 cutoff 统计。"""
    datasets = session.execute(
        text(
            """
            SELECT
                dataset_id, slug, dataset_name, description,
                source_software, source_root, created_at, capabilities
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
            capabilities=_capabilities_out(d.get("capabilities"), source_software=d.get("source_software")),
            created_at=d["created_at"],
            updated_at=None,
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
        capabilities=_capabilities_out(
            dataset.get("capabilities"),
            source_software=dataset.get("source_software"),
        ),
        created_at=dataset["created_at"],
        updated_at=None,
        cutoffs=_cutoffs_payload(session, dataset["dataset_id"]),
    )


@router.delete("/datasets/{slug}", response_model=DatasetDeletedOut)
def delete_dataset(slug: str) -> DatasetDeletedOut:
    """删除一个数据集：

    1. 在 ``datasets`` 表上做 ``DELETE`` —— 由 ``ON DELETE CASCADE`` 顺带清掉
       runs / proteins / proteoforms / identification_matches /
       protein_relation_mapping 中所有关联行。
    2. 删掉 ``DATA_ROOT`` 下与该 slug 关联的解压目录（如果存在）；为安全起见
       只允许在 ``DATA_ROOT`` 子树内执行 ``rmtree``。
    3. 若有进行中的导入任务还指向同一个 slug，会拒绝删除（防止竞争）。
    """
    try:
        result = import_jobs.delete_dataset(slug)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset not found: {slug}") from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return DatasetDeletedOut(
        slug=slug,
        deleted_db=result.deleted_db,
        deleted_disk=result.deleted_disk,
        folder=result.folder,
        folder_existed=result.folder_existed,
    )
