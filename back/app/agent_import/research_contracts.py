"""Structured output and audit records for Agent 1 dataset research."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_import.contracts import AgentAnalysisCategory


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlueprintEvidence(_StrictModel):
    evidence_id: str = Field(..., min_length=1, max_length=120)
    kind: Literal["local_tool", "web_source", "user_input", "inference"]
    reference: str = Field(..., min_length=1, max_length=1000)
    fact: str = Field(..., min_length=1, max_length=2000)


class BlueprintSourceAsset(_StrictModel):
    relative_path: str = Field(..., min_length=1, max_length=500)
    role: str = Field(..., min_length=1, max_length=120)
    media_type: str = Field(..., min_length=1, max_length=120)
    content_summary: str = Field(..., min_length=1, max_length=2000)
    required_for_default_import: bool
    evidence_ids: list[str] = Field(..., min_length=1, max_length=30)
    details: dict[str, Any] = Field(default_factory=dict)


class BlueprintEntity(_StrictModel):
    entity_name: str = Field(..., min_length=1, max_length=120)
    scientific_level: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=2000)
    source_fields: list[str] = Field(default_factory=list, max_length=200)
    identifiers: list[str] = Field(default_factory=list, max_length=50)
    relationships: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=30)
    details: dict[str, Any] = Field(default_factory=dict)


class BlueprintBinaryContent(_StrictModel):
    logical_section: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    source_assets: list[str] = Field(..., min_length=1, max_length=50)
    required: bool
    loss_policy: str = Field(..., min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=30)
    details: dict[str, Any] = Field(default_factory=dict)


class BlueprintVisualization(_StrictModel):
    view_id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    purpose: str = Field(..., min_length=1, max_length=2000)
    entities: list[str] = Field(..., min_length=1, max_length=50)
    visual_components: list[str] = Field(..., min_length=1, max_length=100)
    interactions: list[str] = Field(default_factory=list, max_length=100)
    prerequisites: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=30)
    details: dict[str, Any] = Field(default_factory=dict)


class BlueprintDefaultImport(_StrictModel):
    profile_name: str = Field(..., min_length=1, max_length=160)
    match_rules: list[str] = Field(..., min_length=1, max_length=100)
    required_assets: list[str] = Field(..., min_length=1, max_length=50)
    optional_assets: list[str] = Field(default_factory=list, max_length=100)
    variability_rules: list[str] = Field(default_factory=list, max_length=100)
    editable_fields: list[str] = Field(default_factory=list, max_length=100)
    unsafe_automatic_assumptions: list[str] = Field(default_factory=list, max_length=100)


class BlueprintGap(_StrictModel):
    gap: str = Field(..., min_length=1, max_length=1000)
    consequence: str = Field(..., min_length=1, max_length=1000)
    resolution: str = Field(..., min_length=1, max_length=1000)


class BlueprintCapabilityAssessment(_StrictModel):
    capability_id: str = Field(..., min_length=1, max_length=160, description="Globally unique across ALL levels. Use distinct IDs such as entity.spectra and view.spectra; do not reuse the same ID for an entity and its view.")
    level: Literal["entity", "relationship", "view"]
    state: Literal["DIRECT", "DERIVED", "MISSING", "AMBIGUOUS", "VIEWER_UNSUPPORTED"]
    reason: str = Field(..., min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=30)
    derivation_id: str | None = Field(default=None, max_length=160)
    unlocks: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _derived_has_algorithm(self) -> "BlueprintCapabilityAssessment":
        if self.state == "DERIVED" and not self.derivation_id:
            raise ValueError("DERIVED capability assessment requires derivation_id")
        if self.state != "DERIVED" and self.derivation_id is not None:
            raise ValueError("derivation_id is allowed only for DERIVED assessments")
        return self


class BlueprintCitation(_StrictModel):
    title: str = Field(..., min_length=1, max_length=500)
    url: str = Field(..., min_length=8, max_length=2000)
    supports: list[str] = Field(..., min_length=1, max_length=30)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith(("https://", "http://")):
            raise ValueError("citation URL must use http or https")
        return cleaned


class DatasetBlueprint(_StrictModel):
    schema_version: Literal[1] = 1
    dataset_family: str = Field(..., min_length=1, max_length=160)
    source_profile: str = Field(..., min_length=1, max_length=160)
    analysis_category: AgentAnalysisCategory
    executive_summary: str = Field(..., min_length=1, max_length=6000)
    source_assets: list[BlueprintSourceAsset] = Field(..., min_length=1, max_length=200)
    scientific_entities: list[BlueprintEntity] = Field(..., min_length=1, max_length=200)
    binary_content: list[BlueprintBinaryContent] = Field(..., min_length=1, max_length=200)
    visualizations: list[BlueprintVisualization] = Field(..., min_length=1, max_length=100)
    default_import: BlueprintDefaultImport
    evidence: list[BlueprintEvidence] = Field(..., min_length=1, max_length=300)
    gaps: list[BlueprintGap] = Field(default_factory=list, max_length=100)
    capability_assessments: list[BlueprintCapabilityAssessment] = Field(default_factory=list, max_length=300)
    citations: list[BlueprintCitation] = Field(..., max_length=100)
    acceptance_criteria: list[str] = Field(..., min_length=1, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _evidence_references_exist(self) -> "DatasetBlueprint":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Blueprint evidence_id values must be unique")
        capability_ids = [item.capability_id for item in self.capability_assessments]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("Blueprint capability_id values must be unique")
        declared = set(evidence_ids)
        referenced = {
            evidence_id
            for collection in (
                self.source_assets,
                self.scientific_entities,
                self.binary_content,
                self.visualizations,
                self.capability_assessments,
            )
            for item in collection
            for evidence_id in item.evidence_ids
        }
        if not referenced.issubset(declared):
            raise ValueError("Blueprint references an undeclared evidence_id")
        return self


class ResearchTraceEntry(_StrictModel):
    round_no: int = Field(..., ge=1, le=32)
    call_id: str = Field(..., min_length=1, max_length=200)
    tool_name: str = Field(..., min_length=1, max_length=120)
    arguments: dict[str, Any]
    status: Literal["SUCCEEDED", "FAILED"]
    result_bytes: int = Field(..., ge=0)
    result_summary: str = Field(..., max_length=500)
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ResearchObservation(_StrictModel):
    call_id: str = Field(..., min_length=1, max_length=200)
    tool_name: str = Field(..., min_length=1, max_length=120)
    status: Literal["SUCCEEDED", "FAILED"]
    result_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]


class AgentResearchResult(_StrictModel):
    schema_version: Literal[1] = 1
    provider: Literal["moonshot-kimi-k3", "openai-compatible"] = "openai-compatible"
    model: str = Field(..., min_length=1, max_length=120)
    blueprint: DatasetBlueprint
    trace: list[ResearchTraceEntry] = Field(..., min_length=1, max_length=200)
    observations: list[ResearchObservation] = Field(default_factory=list, max_length=64)
    local_tool_calls: int = Field(..., ge=1)
    web_search_calls: int = Field(..., ge=0)
    fetch_calls: int = Field(..., ge=0)
