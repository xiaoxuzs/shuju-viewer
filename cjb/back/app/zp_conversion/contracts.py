"""Stable contracts for Viewer-managed .zp conversion jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


ZpJobStatus = Literal["queued", "running", "cancelling", "success", "failed", "cancelled"]
ZpJobStage = Literal["queued", "inspect", "convert", "validate", "commit", "success", "failed", "cancelled"]

TERMINAL_STATUSES = {"success", "failed", "cancelled"}


PUBLIC_ERROR_MESSAGES: dict[str, str] = {
    "ZP_SOURCE_PATH_REQUIRED": "source_path is required.",
    "ZP_SOURCE_NOT_FOUND": "Source path does not exist.",
    "ZP_SOURCE_UNSUPPORTED_PATH_TYPE": "Source path must be a file or directory.",
    "ZP_SOURCE_OUTSIDE_ALLOWED_ROOT": "Source path is outside the allowed ZP conversion roots.",
    "ZP_OUTPUT_ROOT_UNAVAILABLE": "ZP output root is unavailable.",
    "ZP_JOB_NOT_FOUND": "ZP conversion job was not found.",
    "ZP_JOB_NOT_ACTIVE": "ZP conversion job is not active.",
    "ZP_WORKER_NOT_CONFIGURED": "ZP worker is not configured on this server.",
    "ZP_WORKER_TIMEOUT": "ZP worker timed out.",
    "ZP_WORKER_FAILED": "ZP worker failed.",
    "ZP_WORKER_CANCELLED": "ZP conversion was cancelled.",
    "ZP_WORKER_INVALID_RESULT": "ZP worker returned an invalid result.",
    "ZP_FINAL_ALREADY_EXISTS": "ZP artifact already exists for this job.",
    "ZP_INTERNAL_ERROR": "ZP conversion failed.",
}


class ZpConversionError(Exception):
    """Exception with a stable public code and path-safe message."""

    def __init__(self, code: str, message: str | None = None, *, status_code: int = 400) -> None:
        self.code = code
        self.message = message or PUBLIC_ERROR_MESSAGES.get(code, PUBLIC_ERROR_MESSAGES["ZP_INTERNAL_ERROR"])
        self.status_code = status_code
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class ZpConversionJob:
    job_id: str
    status: ZpJobStatus
    stage: str | None
    progress: float
    dataset_slug: str | None
    input_root: Path
    zp_temp_path: Path | None
    zp_final_path: Path | None
    format_version: int
    worker_pid: int | None = None
    binary_layer_version: str | None = None
    input_bytes: int | None = None
    output_bytes: int | None = None
    output_sha256: str | None = None
    validation_mode: str | None = None
    validation_certificate_path: Path | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def public_error_message(self) -> str | None:
        if self.error_code is None:
            return None
        return PUBLIC_ERROR_MESSAGES.get(self.error_code, PUBLIC_ERROR_MESSAGES["ZP_INTERNAL_ERROR"])


@dataclass(frozen=True, slots=True)
class ZpArtifact:
    asset_id: int
    dataset_id: int
    run_id: int | None
    zp_path: Path
    format_version: int
    source_fingerprint: str | None
    output_sha256: str
    status: str
    capabilities: dict[str, object]
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ZpJobPaths:
    temp_dir: Path
    partial_path: Path
    final_path: Path
    certificate_path: Path
