"""数据集与 cutoff 的 API 输出模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CutoffOut(BaseModel):
    """单个 cutoff：种类标签及三种实体计数。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    label: str
    protein_count: int = 0
    proteoform_count: int = 0
    prsm_count: int = 0


class DatasetOut(BaseModel):
    """数据集卡片/详情：基本字段 + 嵌套 cutoff 列表。

    universal schema 的 ``datasets`` 表只有 ``created_at``，没有 ``updated_at``
    列；该字段保留为可选，前端用到时按 None 处理。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None
    source_path: str
    capabilities: dict[str, object] = {}
    created_at: datetime
    updated_at: datetime | None = None
    cutoffs: list[CutoffOut] = []


class DatasetDeletedOut(BaseModel):
    """`DELETE /datasets/{slug}` 的应答：仅删除数据库行；``deleted_disk`` 恒为 False。"""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    deleted_db: bool
    deleted_disk: bool
    folder: str | None = None
    folder_existed: bool = False
