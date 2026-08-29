"""Strict model-to-executor contracts for Agent-owned ZP work."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AgentAnalysisCategory = Literal["SPECTRA_ONLY", "TOP_DOWN", "BOTTOM_UP"]
AgentBinaryOperation = Literal["register_existing_zp", "convert_supported_binary_to_zp"]

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


class ZpConversionPlan(BaseModel):
    relative_source: str = Field(..., min_length=1, max_length=500)
    target_format_version: int | None = Field(default=None, ge=1, le=3)

    @field_validator("relative_source")
    @classmethod
    def _case_relative_source(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or _WINDOWS_DRIVE.match(normalized):
            raise ValueError("relative_source must be relative to the Case source root")
        if any(part == ".." for part in path.parts):
            raise ValueError("relative_source cannot escape the Case source root")
        return path.as_posix()


class AgentCandidatePlan(BaseModel):
    schema_version: Literal[1] = 1
    analysis_category: AgentAnalysisCategory
    source_profile: str = Field(..., min_length=1, max_length=160)
    binary_operation: AgentBinaryOperation
    zp_conversion_plan: ZpConversionPlan

    @field_validator("source_profile")
    @classmethod
    def _clean_source_profile(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_profile is required")
        return cleaned

    @model_validator(mode="after")
    def _operation_matches_source(self) -> "AgentCandidatePlan":
        if (
            self.binary_operation == "register_existing_zp"
            and not self.zp_conversion_plan.relative_source.casefold().endswith(".zp")
        ):
            raise ValueError("register_existing_zp requires a .zp relative_source")
        return self
