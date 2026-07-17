"""Upload API and manifest contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportType(str, Enum):
    RAW_ONLY = "RAW_ONLY"
    MZML_ONLY = "MZML_ONLY"
    TOPPIC = "TOPPIC"
    PRSM = "PRSM"
    DIA_NN = "DIA_NN"


class UploadState(str, Enum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    READY = "READY"
    STARTED = "STARTED"
    FAILED = "FAILED"


class UploadFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str
    size_bytes: int = Field(ge=0)
    completed: Literal[True] = True


class UploadManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1] = 1
    upload_id: str
    import_type: ImportType
    state: UploadState
    created_at: datetime
    started_at: datetime | None = None
    job_id: str | None = None
    total_size_bytes: int = Field(default=0, ge=0)
    files: list[UploadFileRecord] = Field(default_factory=list)


class ImportUploadCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_type: ImportType


class ImportUploadStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameters: dict[str, Any]


class ImportUploadCreatedOut(BaseModel):
    upload_id: str
    import_type: ImportType
    state: UploadState
    created_at: datetime


class ImportUploadFileOut(BaseModel):
    upload_id: str
    relative_path: str
    size_bytes: int
    state: UploadState
    total_size_bytes: int
    file_count: int


class ImportUploadSessionOut(BaseModel):
    upload_id: str
    import_type: ImportType
    state: UploadState
    file_count: int
    total_size_bytes: int
    job_id: str | None
    created_at: datetime
    started_at: datetime | None
