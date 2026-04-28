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
    """数据集卡片/详情：基本字段 + 嵌套 cutoff 列表。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None
    source_path: str
    created_at: datetime
    updated_at: datetime
    cutoffs: list[CutoffOut] = []
