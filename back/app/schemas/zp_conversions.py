"""Pydantic models for ZP conversion management APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ZpConversionCreateIn(BaseModel):
    source_path: str = Field(..., min_length=1, description="Server-side source path under a trusted root.")
    dataset_slug: str | None = Field(None, description="Existing or intended Viewer dataset slug.")
    format_version: int | None = Field(
        None,
        ge=1,
        le=3,
        description="Explicit ZP format version; defaults to server config.",
    )

    @model_validator(mode="after")
    def _clean_slug(self) -> "ZpConversionCreateIn":
        if self.dataset_slug is not None:
            self.dataset_slug = self.dataset_slug.strip() or None
        return self


class ZpConversionCreatedOut(BaseModel):
    job_id: str
    status: str


class ZpConversionJobOut(BaseModel):
    job_id: str
    status: str
    stage: str | None = None
    progress: float = Field(0.0, ge=0.0, le=100.0)
    dataset_slug: str | None = None
    format_version: int
    input_bytes: int | None = None
    output_bytes: int | None = None
    output_sha256: str | None = None
    validation_mode: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None


class ZpAssetOut(BaseModel):
    asset_id: int
    dataset_id: int
    run_id: int | None = None
    format_version: int
    output_sha256: str
    status: str
    capabilities: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ZpDatasetStatusOut(BaseModel):
    dataset_id: int
    has_active_zp: bool
    active_asset_count: int
    assets: list[ZpAssetOut]
    latest_job: ZpConversionJobOut | None = None


class ZpExtensionSummaryOut(BaseModel):
    extension_type: str
    extension_version: str
    owner: str | None = None
    schema_name: str | None = None
    schema_version: int | str | None = None
    record_count: int | None = None


class ZpExtensionListOut(BaseModel):
    dataset_id: int
    extensions: list[ZpExtensionSummaryOut]


class ZpExtensionPayloadOut(BaseModel):
    dataset_id: int
    extension_type: str
    extension_version: str
    owner: str | None = None
    schema_name: str | None = None
    schema_version: int | str | None = None
    record_count: int | None = None
    offset: int = 0
    limit: int = 100
    returned_record_count: int | None = None
    payload: dict[str, Any]
