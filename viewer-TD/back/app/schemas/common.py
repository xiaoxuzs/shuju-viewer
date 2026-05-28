"""Common response schemas (pagination, etc.)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Paging wrapper: ``items`` is the current page; ``total`` is all matching rows after filters (not page size)."""

    items: list[T]
    total: int = Field(description="Total rows matching the filters.")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)
