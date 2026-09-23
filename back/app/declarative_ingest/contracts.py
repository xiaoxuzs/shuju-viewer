"""Strict model-to-executor contract for format-neutral source mappings."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


SourceReaderId = Literal["delimited", "jsonl", "parquet", "mzml", "fasta"]
ValueKind = Literal["integer", "float", "string", "boolean"]
TargetEntity = Literal[
    "run",
    "spectrum",
    "identification",
    "peptide",
    "protein",
    "protein_group",
    "modification",
    "quantification",
]
TransformId = Literal[
    "identity",
    "trim",
    "minute_to_second",
    "semicolon_split",
    "singleton_list",
    "first_semicolon_value",
    "plus_marker_to_bool",
]
RelationshipKind = Literal[
    "identification_to_spectrum",
    "identification_to_peptide",
    "identification_to_protein",
    "identification_to_protein_group",
    "peptide_to_protein",
    "protein_to_protein_group",
]
Cardinality = Literal["one_to_one", "many_to_one", "many_to_many"]
FailurePolicy = Literal["BLOCK_DATASET", "DISABLE_MODULE"]

PlanId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def case_relative_path(value: str, *, field_name: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or _WINDOWS_DRIVE.match(normalized):
        raise ValueError(f"{field_name} must be relative to the Case source root")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not escape or alias the Case source root")
    return path.as_posix()


class DeclarativeSource(_StrictModel):
    source_id: PlanId
    relative_path: str = Field(..., min_length=1, max_length=500)
    role: str = Field(..., min_length=1, max_length=120)
    reader: SourceReaderId
    required: bool = True
    delimiter: Literal[",", "\t", ";", "|"] | None = None
    required_fields: list[str] = Field(default_factory=list, max_length=300)
    fasta_accession_rule: Literal["first_token", "uniprot_pipe_accession"] | None = None
    accession_rule_evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    identification_identity: Literal["mapped", "source_row"] = "mapped"

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return case_relative_path(value, field_name="relative_path")

    @field_validator("required_fields")
    @classmethod
    def _unique_fields(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("required_fields must contain unique non-empty names")
        return cleaned

    @model_validator(mode="after")
    def _delimiter_matches_reader(self) -> "DeclarativeSource":
        if self.identification_identity == "source_row" and self.reader not in {"delimited", "jsonl", "parquet"}:
            raise ValueError("source_row identity requires a tabular source")
        if self.reader == "delimited" and self.delimiter is None:
            raise ValueError("delimited sources require an explicit delimiter")
        if self.reader != "delimited" and self.delimiter is not None:
            raise ValueError("delimiter is allowed only for delimited sources")
        if self.reader == "fasta":
            self.fasta_accession_rule = self.fasta_accession_rule or "first_token"
            if self.fasta_accession_rule != "first_token" and not self.accession_rule_evidence_refs:
                raise ValueError("non-default FASTA accession rules require evidence references")
        elif self.fasta_accession_rule is not None or self.accession_rule_evidence_refs:
            raise ValueError("FASTA accession rules are allowed only for FASTA sources")
        return self


class FieldMapping(_StrictModel):
    mapping_id: PlanId
    source_id: PlanId
    source_field: str = Field(..., min_length=1, max_length=240)
    target_entity: TargetEntity
    target_field: str = Field(..., min_length=1, max_length=160)
    value_kind: ValueKind
    required: bool = False
    unit: str | None = Field(default=None, max_length=80)
    measurement_name: str | None = Field(default=None, min_length=1, max_length=120,
        description="Explicit labelled quantitative channel (for example an evidenced reporter channel), not a metric or display name. Omit for unlabelled source intensity; the source field is retained separately as metric.")
    transform: TransformId = "identity"
    evidence_refs: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("source_field", "target_field")
    @classmethod
    def _clean_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field names cannot be blank")
        return cleaned

    @field_validator("evidence_refs")
    @classmethod
    def _evidence_is_unique(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("evidence_refs must contain unique non-empty references")
        return cleaned

    @model_validator(mode="after")
    def _measurement_name_scope(self) -> "FieldMapping":
        is_measurement = self.target_entity == "quantification" and self.target_field == "value"
        if self.measurement_name is not None and not is_measurement:
            raise ValueError("measurement_name is allowed only for quantification.value")
        return self


class JoinRule(_StrictModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"allOf": [{
        "if": {"properties": {"required": {"const": False}}, "required": ["required"]},
        "then": {"properties": {"on_failure": {"const": "DISABLE_MODULE"}}},
        "else": {"properties": {"on_failure": {"const": "BLOCK_DATASET"}}},
    }]})
    join_id: PlanId
    relationship: Literal["identification_to_spectrum"]
    left_source_id: PlanId
    left_field: str = Field(..., min_length=1, max_length=240)
    right_source_id: PlanId
    right_field: str = Field(..., min_length=1, max_length=240)
    cardinality: Cardinality
    transform: Literal["identity", "semicolon_membership", "first_semicolon_value"] = "identity"
    required: bool = Field(default=True, description="True requires every identification row to resolve and blocks the dataset on any unmatched row. False retains unmatched rows with an unavailable link. This is independent of whether the mzML input file itself is required; follow the Blueprint's unmatched-row policy.")
    on_failure: FailurePolicy = Field(default="BLOCK_DATASET", description="Required joins use BLOCK_DATASET; optional joins use DISABLE_MODULE. Explicit mismatches are invalid.")
    evidence_refs: list[str] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def _default_failure_policy(cls, value):
        if isinstance(value, dict) and "on_failure" not in value:
            return {**value, "on_failure": "DISABLE_MODULE" if value.get("required", True) is False else "BLOCK_DATASET"}
        return value

    @model_validator(mode="after")
    def _failure_policy_matches_requiredness(self) -> "JoinRule":
        expected = "BLOCK_DATASET" if self.required else "DISABLE_MODULE"
        if self.on_failure != expected:
            raise ValueError(f"join on_failure must be {expected} when required={self.required}")
        return self


class RequestedView(_StrictModel):
    view_id: str = Field(..., min_length=1, max_length=160, description="A capability-report request, not an execution claim. Unknown optional IDs are explicitly reported DISABLED/VIEWER_UNSUPPORTED with no route.")
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AssetDisposition(_StrictModel):
    relative_path: str = Field(..., min_length=1, max_length=500)
    disposition: Literal["PROVENANCE_ONLY", "IRRELEVANT", "UNSUPPORTED"]
    reason: str = Field(..., min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return case_relative_path(value, field_name="asset disposition relative_path")


class DeclarativeImportPlan(_StrictModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "allOf": [{
            "if": {"properties": {"sources": {"contains": {
                "type": "object", "properties": {"reader": {"const": "mzml"}}, "required": ["reader"],
            }}}, "required": ["sources"]},
            "then": {
                "required": ["acquisition_mode", "acquisition_mode_evidence_refs"],
                "properties": {
                    "acquisition_mode": {"type": "string", "enum": ["dda", "dia"]},
                    "acquisition_mode_evidence_refs": {"type": "array", "minItems": 1},
                },
            },
            "else": {"properties": {
                "acquisition_mode": {"type": "null"},
                "acquisition_mode_evidence_refs": {"type": "array", "maxItems": 0},
            }},
        }],
    })
    schema_version: Literal[1] = 1
    plan_id: PlanId
    analysis_mode: Literal["BOTTOM_UP"] = "BOTTOM_UP"
    acquisition_mode: Literal["dda", "dia"] | None = None
    acquisition_mode_evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    sources: list[DeclarativeSource] = Field(..., min_length=1, max_length=50)
    field_mappings: list[FieldMapping] = Field(..., min_length=1, max_length=500)
    join_rules: list[JoinRule] = Field(default_factory=list, max_length=100)
    unmapped_fields: dict[str, list[str]] = Field(default_factory=dict)
    requested_views: list[RequestedView] = Field(default_factory=list, max_length=100)
    asset_dispositions: list[AssetDisposition] = Field(default_factory=list, max_length=5_000)

    @model_validator(mode="after")
    def _references_are_consistent(self) -> "DeclarativeImportPlan":
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("sources must use unique source_id values")
        declared = set(source_ids)
        mapping_ids = [item.mapping_id for item in self.field_mappings]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise ValueError("field_mappings must use unique mapping_id values")
        join_ids = [item.join_id for item in self.join_rules]
        if len(join_ids) != len(set(join_ids)):
            raise ValueError("join_rules must use unique join_id values")
        referenced = {
            *(item.source_id for item in self.field_mappings),
            *(item.left_source_id for item in self.join_rules),
            *(item.right_source_id for item in self.join_rules),
            *self.unmapped_fields.keys(),
        }
        if not referenced.issubset(declared):
            raise ValueError("plan references an undeclared source_id")
        for source_id, fields in self.unmapped_fields.items():
            cleaned = [item.strip() for item in fields]
            if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
                raise ValueError(f"unmapped_fields[{source_id}] must contain unique non-empty names")
            self.unmapped_fields[source_id] = cleaned
        view_ids = [item.view_id for item in self.requested_views]
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("requested_views must use unique view_id values")
        disposition_paths = [item.relative_path for item in self.asset_dispositions]
        if len(disposition_paths) != len(set(disposition_paths)):
            raise ValueError("asset_dispositions must use unique relative_path values")
        source_paths = {item.relative_path for item in self.sources}
        if source_paths.intersection(disposition_paths):
            raise ValueError("an input source cannot also be a non-input asset disposition")
        has_mzml = any(item.reader == "mzml" for item in self.sources)
        if has_mzml and (self.acquisition_mode is None or not self.acquisition_mode_evidence_refs):
            raise ValueError("mzML plans require an evidence-backed acquisition_mode")
        if not has_mzml and (self.acquisition_mode is not None or self.acquisition_mode_evidence_refs):
            raise ValueError("acquisition_mode is allowed only when an mzML source is declared")
        return self
