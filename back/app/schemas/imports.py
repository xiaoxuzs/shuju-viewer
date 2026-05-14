"""Import job API models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImportEnqueueIn(BaseModel):
    """Request body for path-based dataset import."""

    source_path: str = Field(..., min_length=1, description="Absolute or user-home path to a folder on the server.")
    slug: str = Field(..., min_length=1, description="Unique slug for URLs.")
    name: str = Field(..., min_length=1, description="Human-readable dataset name.")
    description: str | None = Field(None, description="Optional description.")


class ImportJobOut(BaseModel):
    """Status of a dataset import started from the UI."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str = Field(..., description="Opaque id for polling.")
    status: str = Field(..., description="queued | running | success | failed")
    message: str | None = None
    error: str | None = None
    dataset_slug: str | None = None
    progress: float = Field(
        0.0,
        ge=0.0,
        le=100.0,
        description="Real progress 0..100. 100 only when status == 'success'.",
    )
    stage: str | None = Field(
        None,
        description=(
            "Machine-readable phase: queued | fingerprint | init | proteins | "
            "matches | finalize | success | failed"
        ),
    )
    stage_label: str | None = Field(
        None,
        description="Localized human-readable label for the current phase.",
    )
    stage_detail: str | None = Field(
        None,
        description="Free-form detail line about current progress (e.g. '1234/4567 PrSM details').",
    )
    created_at: datetime
    updated_at: datetime


class ImportJobCreatedOut(BaseModel):
    """Response right after enqueueing an import."""

    job_id: str
    status: str = "queued"


class ImportPickFolderOut(BaseModel):
    """Result of ``POST /imports/pick-folder`` (native dialog on the API host)."""

    path: str | None = None
    cancelled: bool = False
