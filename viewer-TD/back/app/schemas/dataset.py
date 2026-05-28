"""Dataset and cutoff API output models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CutoffOut(BaseModel):
    """One virtual cutoff with entity counts."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    label: str
    protein_count: int = 0
    proteoform_count: int = 0
    prsm_count: int = 0


class DatasetOut(BaseModel):
    """Dataset card/detail with nested cutoff statistics."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None
    source_path: str
    capabilities: dict[str, object] = Field(default_factory=dict)
    analysis_mode: Literal["TOP_DOWN", "BOTTOM_UP"] | None = None
    status: str | None = None
    source_software: str | None = None
    extra_metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None
    cutoffs: list[CutoffOut] = Field(default_factory=list)


class DatasetDeletedOut(BaseModel):
    """Response for ``DELETE /datasets/{slug}``."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    deleted_db: bool
    deleted_disk: bool
    folder: str | None = None
    folder_existed: bool = False
