"""Schemas for the minimal Agent -> ZP import bridge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


AgentZpAnalysisCategory = Literal["SPECTRA_ONLY", "TOP_DOWN", "BOTTOM_UP"]
AgentZpBinaryOperation = Literal["register_existing_zp", "convert_supported_binary_to_zp"]


class AgentZpImportCreateIn(BaseModel):
    source_path: str = Field(..., min_length=1, description="Trusted server-side source path or existing .zp path.")
    slug: str = Field(..., min_length=1, max_length=160)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    analysis_category: AgentZpAnalysisCategory = "SPECTRA_ONLY"
    source_profile: str = Field("agent_zp_candidate", min_length=1, max_length=160)
    binary_operation: AgentZpBinaryOperation = "register_existing_zp"
    format_version: int | None = Field(None, ge=1, le=3)
    replace_existing: bool = False

    @model_validator(mode="after")
    def _clean_text_fields(self) -> "AgentZpImportCreateIn":
        self.source_path = self.source_path.strip()
        self.slug = self.slug.strip()
        self.name = self.name.strip()
        self.description = self.description.strip() if self.description else None
        self.source_profile = self.source_profile.strip()
        if not self.source_path:
            raise ValueError("source_path is required")
        if not self.slug:
            raise ValueError("slug is required")
        if not self.name:
            raise ValueError("name is required")
        if not self.source_profile:
            raise ValueError("source_profile is required")
        return self


class AgentZpRunVerificationOut(BaseModel):
    run_id: int
    run_name: str
    scan_count: int
    sample_scan_number: int
    sample_peak_count: int


class AgentZpVerificationOut(BaseModel):
    validation_mode: str
    scan_index_total: int
    readable_run_count: int
    runs: list[AgentZpRunVerificationOut]


class AgentZpImportOut(BaseModel):
    case_id: str
    status: str
    binary_operation: AgentZpBinaryOperation
    analysis_category: AgentZpAnalysisCategory
    source_profile: str
    dataset_id: int
    dataset_slug: str
    run_ids: list[int]
    zp_format_version: int
    zp_output_sha256: str
    validation_mode: str
    verification: AgentZpVerificationOut
