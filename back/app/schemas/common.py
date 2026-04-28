"""通用响应模型（分页等）。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """分页包装：``items`` 为当前页数据，``total`` 为过滤后总行数（非仅本页）。"""

    items: list[T]
    total: int = Field(description="符合筛选条件的总行数。")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)
