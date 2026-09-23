"""Strict data contracts for dataset capability reports."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactState(str, Enum):
    """How strongly a dataset fact is supported."""

    DIRECT = "DIRECT"
    DERIVED = "DERIVED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    VIEWER_UNSUPPORTED = "VIEWER_UNSUPPORTED"


class ViewAvailability(str, Enum):
    """Whether Viewer can render a registered view."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    DISABLED = "DISABLED"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntityCapability(_Contract):
    entity: str = Field(min_length=1)
    state: FactState
    count: int | None = Field(default=None, ge=0, strict=True)
    reason_code: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    derivation_id: str | None = None

    @model_validator(mode="after")
    def require_derived_provenance(self) -> "EntityCapability":
        if self.state is FactState.DERIVED and not self.derivation_id:
            raise ValueError("DERIVED entity facts require derivation_id")
        return self


class ViewRequirement(_Contract):
    entity: str = Field(min_length=1)
    state: FactState
    required: bool = Field(default=True, strict=True)
    reason_code: str | None = None
    derivation_id: str | None = None

    @model_validator(mode="after")
    def require_derived_provenance(self) -> "ViewRequirement":
        if self.state is FactState.DERIVED and not self.derivation_id:
            raise ValueError("DERIVED view requirements require derivation_id")
        return self


class ViewCapability(_Contract):
    view_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    route: str
    availability: ViewAvailability
    requirements: list[ViewRequirement] = Field(default_factory=list)
    reason_code: str | None = None
    message: str | None = None


class MissingInput(_Contract):
    input_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    unlocks: list[str] = Field(default_factory=list)


class CapabilityAmbiguity(_Contract):
    ambiguity_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    affected_views: list[str] = Field(default_factory=list)


class CapabilityWarning(_Contract):
    warning_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class ValidatedDatasetFacts(_Contract):
    """Deterministically verified facts accepted by the report compiler."""

    dataset_id: int = Field(gt=0, strict=True)
    source_case_id: str | None = None
    analysis_mode: Literal["BOTTOM_UP", "TOP_DOWN", "SPECTRA_ONLY"] | None = None
    entities: list[EntityCapability] = Field(default_factory=list)
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    ambiguities: list[CapabilityAmbiguity] = Field(default_factory=list)
    warnings: list[CapabilityWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "ValidatedDatasetFacts":
        _require_unique((item.entity for item in self.entities), "entity")
        _require_unique((item.input_id for item in self.missing_inputs), "missing input")
        _require_unique((item.ambiguity_id for item in self.ambiguities), "ambiguity")
        _require_unique((item.warning_id for item in self.warnings), "warning")
        return self


class DatasetCapabilityReport(_Contract):
    schema_version: Literal[1] = 1
    dataset_id: int = Field(gt=0, strict=True)
    source_case_id: str | None = None
    provenance: Literal["VALIDATED_FACTS", "LEGACY_METADATA"] = "VALIDATED_FACTS"
    enforcement: Literal["ENFORCED", "ADVISORY"] = "ENFORCED"
    entities: list[EntityCapability] = Field(default_factory=list)
    views: list[ViewCapability] = Field(default_factory=list)
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    ambiguities: list[CapabilityAmbiguity] = Field(default_factory=list)
    warnings: list[CapabilityWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "DatasetCapabilityReport":
        if (self.provenance, self.enforcement) not in {
            ("VALIDATED_FACTS", "ENFORCED"),
            ("LEGACY_METADATA", "ADVISORY"),
        }:
            raise ValueError("capability report provenance and enforcement are inconsistent")
        _require_unique((item.entity for item in self.entities), "entity")
        _require_unique((item.view_id for item in self.views), "view")
        _require_unique((item.input_id for item in self.missing_inputs), "missing input")
        _require_unique((item.ambiguity_id for item in self.ambiguities), "ambiguity")
        _require_unique((item.warning_id for item in self.warnings), "warning")
        return self


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label} id: {value}")
        seen.add(value)
