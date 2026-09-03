"""Strict model-to-executor contracts for Agent-owned ZP work."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


AgentAnalysisCategory = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[^\x00-\x1f\x7f-\x9f]+$",
    ),
]
AgentBinaryOperation = Literal[
    "register_existing_zp",
    "convert_supported_binary_to_zp",
    "convert_declared_mapping_to_zp",
]
AgentCandidateStatus = Literal["READY", "NEEDS_USER", "UNSUPPORTED"]
AgentReviewStatus = Literal["APPROVED", "NEEDS_USER", "REJECTED"]
MappingSourceFormat = Literal["csv", "tsv", "json", "jsonl", "xml", "mzml", "fasta", "vendor"]
MappingValueKind = Literal["integer", "float", "string", "boolean"]
MappingTargetEntity = Literal[
    "metadata",
    "run",
    "spectrum",
    "precursor",
    "identification",
    "peptide",
    "protein",
    "protein_group",
    "modification",
    "quantification",
]
MappingTransform = Literal[
    "identity",
    "minute_to_second",
    "semicolon_split",
    "first_semicolon_value",
    "plus_marker_to_bool",
]

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _case_relative(value: str, *, field_name: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or _WINDOWS_DRIVE.match(normalized):
        raise ValueError(f"{field_name} must be relative to the Case source root")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} cannot escape the Case source root")
    return path.as_posix()


class ZpMappingSourceFile(_StrictModel):
    relative_path: str = Field(..., min_length=1, max_length=500)
    role: str = Field(..., min_length=1, max_length=80)
    source_format: MappingSourceFormat
    required: bool = True
    required_columns: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return _case_relative(value, field_name="relative_path")

    @field_validator("required_columns")
    @classmethod
    def _unique_required_columns(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("required_columns must contain unique non-empty names")
        return cleaned


class ZpFieldMapping(_StrictModel):
    source_file: str = Field(..., min_length=1, max_length=500)
    source_field: str = Field(..., min_length=1, max_length=200)
    target_entity: MappingTargetEntity
    target_field: str = Field(..., min_length=1, max_length=160)
    value_kind: MappingValueKind
    required: bool = False
    unit: str | None = Field(default=None, max_length=80)
    transform: MappingTransform = "identity"
    evidence: str = Field(..., min_length=1, max_length=500)

    @field_validator("source_file")
    @classmethod
    def _relative_source_file(cls, value: str) -> str:
        return _case_relative(value, field_name="source_file")


class ZpJoinRule(_StrictModel):
    left_file: str = Field(..., min_length=1, max_length=500)
    left_field: str = Field(..., min_length=1, max_length=200)
    right_file: str = Field(..., min_length=1, max_length=500)
    right_field: str = Field(..., min_length=1, max_length=200)
    cardinality: Literal["many_to_one", "one_to_one"]
    transform: Literal["identity", "semicolon_membership", "first_semicolon_value"] = "identity"

    @field_validator("left_file", "right_file")
    @classmethod
    def _relative_join_file(cls, value: str) -> str:
        return _case_relative(value, field_name="join file")


class ZpMappingEvidence(_StrictModel):
    source_file: str = Field(..., min_length=1, max_length=500)
    source_field: str | None = Field(default=None, max_length=200)
    fact: str = Field(..., min_length=1, max_length=500)

    @field_validator("source_file")
    @classmethod
    def _relative_evidence_file(cls, value: str) -> str:
        return _case_relative(value, field_name="evidence source_file")


class ZpMappingPlan(_StrictModel):
    schema_version: Literal[1] = 1
    adapter_id: str = Field(..., min_length=1, max_length=100)
    source_format: str = Field(..., min_length=1, max_length=100)
    target_format_version: Literal[3] = 3
    source_files: list[ZpMappingSourceFile] = Field(..., min_length=1, max_length=20)
    field_mappings: list[ZpFieldMapping] = Field(..., min_length=1, max_length=300)
    join_rules: list[ZpJoinRule] = Field(default_factory=list, max_length=20)
    row_policy: Literal["preserve_all_rows", "filter_declared_rows"] = "preserve_all_rows"
    unmapped_fields: dict[str, list[str]] = Field(default_factory=dict)
    expected_counts: dict[str, int] = Field(default_factory=dict)
    evidence: list[ZpMappingEvidence] = Field(..., min_length=1, max_length=30)

    @model_validator(mode="after")
    def _references_declared_files(self) -> "ZpMappingPlan":
        files = [item.relative_path for item in self.source_files]
        if len(files) != len(set(files)):
            raise ValueError("source_files paths must be unique")
        declared = set(files)
        referenced = {
            *(item.source_file for item in self.field_mappings),
            *(item.left_file for item in self.join_rules),
            *(item.right_file for item in self.join_rules),
            *(item.source_file for item in self.evidence),
            *self.unmapped_fields.keys(),
        }
        if not referenced.issubset(declared):
            raise ValueError("mapping plan references an undeclared source file")
        for source_file, fields in self.unmapped_fields.items():
            cleaned = [item.strip() for item in fields]
            if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
                raise ValueError(f"unmapped_fields[{source_file}] must contain unique non-empty names")
            self.unmapped_fields[source_file] = cleaned
        if any(
            not key or isinstance(value, bool) or not isinstance(value, int) or value < 0
            for key, value in self.expected_counts.items()
        ):
            raise ValueError("expected_counts must contain non-negative integer values")
        return self


class ZpConversionPlan(_StrictModel):
    relative_source: str = Field(..., min_length=1, max_length=500)
    target_format_version: int | None = Field(default=None, ge=1, le=3)
    mapping_plan: ZpMappingPlan | None = None

    @field_validator("relative_source")
    @classmethod
    def _case_relative_source(cls, value: str) -> str:
        return _case_relative(value, field_name="relative_source")


class AgentCandidatePlan(_StrictModel):
    schema_version: Literal[1, 2] = 1
    status: AgentCandidateStatus = "READY"
    analysis_category: AgentAnalysisCategory
    source_profile: str = Field(..., min_length=1, max_length=160)
    binary_operation: AgentBinaryOperation | None = None
    zp_conversion_plan: ZpConversionPlan | None = None
    questions: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("source_profile")
    @classmethod
    def _clean_source_profile(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_profile is required")
        return cleaned

    @field_validator("questions")
    @classmethod
    def _clean_questions(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("questions cannot contain empty items")
        return cleaned

    @model_validator(mode="after")
    def _decision_is_consistent(self) -> "AgentCandidatePlan":
        if self.status != "READY":
            if not self.questions:
                raise ValueError("NEEDS_USER and UNSUPPORTED decisions require questions")
            if self.binary_operation is not None or self.zp_conversion_plan is not None:
                raise ValueError("a non-ready decision cannot contain an executable operation")
            return self
        if self.binary_operation is None or self.zp_conversion_plan is None:
            raise ValueError("a READY decision requires an executable ZP operation")
        relative_source = self.zp_conversion_plan.relative_source
        if self.binary_operation == "register_existing_zp" and not relative_source.casefold().endswith(".zp"):
            raise ValueError("register_existing_zp requires a .zp relative_source")
        mapping = self.zp_conversion_plan.mapping_plan
        if self.binary_operation == "convert_declared_mapping_to_zp":
            if self.schema_version != 2 or mapping is None:
                raise ValueError("declared mapping conversion requires schema_version=2 and mapping_plan")
            if self.zp_conversion_plan.target_format_version != mapping.target_format_version:
                raise ValueError("mapping and conversion target_format_version must match")
        elif mapping is not None:
            raise ValueError("mapping_plan is allowed only for convert_declared_mapping_to_zp")
        return self


class AgentPlanReview(_StrictModel):
    schema_version: Literal[1] = 1
    status: AgentReviewStatus
    issues: list[str] = Field(default_factory=list, max_length=30)
    questions: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _review_is_actionable(self) -> "AgentPlanReview":
        if self.status == "NEEDS_USER" and not self.questions:
            raise ValueError("NEEDS_USER review requires questions")
        if self.status == "REJECTED" and not self.issues:
            raise ValueError("REJECTED review requires issues")
        return self
