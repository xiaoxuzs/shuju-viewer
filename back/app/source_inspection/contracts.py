"""Strict, JSON-serializable contracts for Case-scoped source inspection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ObservationStatus = Literal["COMPLETE", "PARTIAL", "UNSUPPORTED", "INVALID"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectionLimits(_StrictModel):
    """Hard limits for one file observation.

    Byte limits count bytes actually requested from storage, including repeated
    reads and random-access metadata reads.  They are intentionally not a file
    size limit.
    """

    max_bytes_read: int = Field(default=32 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    max_rows: int = Field(default=100_000, ge=1, le=10_000_000)
    max_elements: int = Field(default=100_000, ge=1, le=10_000_000)
    max_fields: int = Field(default=256, ge=1, le=10_000)
    max_depth: int = Field(default=12, ge=1, le=128)
    max_sample_values: int = Field(default=5, ge=0, le=100)
    max_tracked_distinct: int = Field(default=2_048, ge=1, le=100_000)
    max_seconds: float = Field(default=10.0, gt=0, le=600.0)
    sniff_bytes: int = Field(default=8_192, ge=64, le=1024 * 1024)

    @model_validator(mode="after")
    def _sniff_fits_byte_budget(self) -> "InspectionLimits":
        if self.sniff_bytes > self.max_bytes_read:
            raise ValueError("sniff_bytes cannot exceed max_bytes_read")
        return self


class BudgetUsage(_StrictModel):
    limits: InspectionLimits
    bytes_read: int = Field(..., ge=0)
    rows_read: int = Field(..., ge=0)
    elements_read: int = Field(..., ge=0)
    elapsed_ms: float = Field(..., ge=0)
    exhausted: list[Literal["bytes", "rows", "elements", "time"]] = Field(default_factory=list)


class TruncationInfo(_StrictModel):
    truncated: bool
    reasons: list[str] = Field(default_factory=list, max_length=20)


class ObservationHashes(_StrictModel):
    """Hashes with deliberately distinct scopes.

    ``inspection_sample_sha256`` hashes the bytes read in inspection order and
    must not be treated as a whole-file content digest.  The metadata and
    observation hashes are stable provenance identifiers for their respective
    JSON payloads.
    """

    source_metadata_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    inspection_sample_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    observation_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    source_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    inspection_sample_scope: Literal["bytes-read-in-inspection-order"] = "bytes-read-in-inspection-order"


class SniffResult(_StrictModel):
    relative_path: str = Field(..., min_length=1, max_length=1000)
    extension: str = Field(..., max_length=64)
    detected_format: str = Field(..., min_length=1, max_length=80)
    media_type: str = Field(..., min_length=1, max_length=160)
    encoding: str | None = Field(default=None, max_length=80)
    is_binary: bool
    confidence: Literal["high", "medium", "low"]
    magic_matches: list[str] = Field(default_factory=list, max_length=20)


class ObservationArtifact(_StrictModel):
    """One auditable observation; never contains an absolute source path."""

    schema_version: Literal[1] = 1
    status: ObservationStatus
    relative_path: str = Field(..., min_length=1, max_length=1000)
    source_size_bytes: int = Field(..., ge=0)
    source_mtime_ns: int = Field(..., ge=0)
    detected_format: str = Field(..., min_length=1, max_length=80)
    inspector_id: str = Field(..., min_length=1, max_length=120)
    inspector_version: str = Field(..., min_length=1, max_length=80)
    facts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    budget: BudgetUsage
    truncation: TruncationInfo
    hashes: ObservationHashes


class InventoryItem(_StrictModel):
    relative_path: str = Field(..., min_length=1, max_length=1000)
    kind: Literal["file", "directory"]
    size_bytes: int | None = Field(default=None, ge=0)
    mtime_ns: int = Field(..., ge=0)
    extension: str = Field(default="", max_length=64)


class InventoryPage(_StrictModel):
    schema_version: Literal[1] = 1
    directory: str = Field(..., min_length=1, max_length=1000)
    recursive: bool
    include_directories: bool
    items: list[InventoryItem]
    total_count: int = Field(..., ge=0)
    skipped_link_count: int = Field(..., ge=0)
    cursor: str | None = None
    next_cursor: str | None = None
    snapshot_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    elapsed_ms: float = Field(..., ge=0)
