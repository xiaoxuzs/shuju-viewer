"""Canonical semantic payload stored in a Viewer ZP extension.

The schema intentionally permits missing optional relations. A missing spectrum,
FASTA sequence, fragment annotation, or quantification value is represented as
missing data, never as a fabricated placeholder.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SEMANTIC_EXTENSION_TYPE = "viewer_semantic_dataset"
SEMANTIC_SCHEMA_VERSION = 1
FactState = Literal["DIRECT", "DERIVED", "MISSING", "AMBIGUOUS", "VIEWER_UNSUPPORTED"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticSourceFile(_StrictModel):
    source_id: str
    relative_path: str
    role: str
    reader: str
    size_bytes: int = Field(..., ge=0)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class SemanticAssetDisposition(_StrictModel):
    relative_path: str
    disposition: Literal["PROVENANCE_ONLY", "IRRELEVANT", "UNSUPPORTED"]
    reason: str
    evidence_refs: list[str]


class SemanticRun(_StrictModel):
    run_id: str
    name: str
    source_file: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticIdentification(_StrictModel):
    identification_id: str
    source_record_id: str
    run_id: str
    peptide_id: str
    modified_sequence: str | None = None
    charge: int | None = Field(default=None, gt=0)
    precursor_mz: float | None = Field(default=None, ge=0)
    neutral_mass: float | None = Field(default=None, ge=0)
    rt_seconds: float | None = Field(default=None, ge=0)
    source_scan: int | None = Field(default=None, ge=0)
    source_native_id: str | None = None
    spectrum_id: str | None = None
    spectrum_link_state: FactState
    spectrum_link_derivation_id: str | None = None
    score: float | None = None
    q_value: float | None = Field(default=None, ge=0, le=1)
    pep: float | None = Field(default=None, ge=0, le=1)
    protein_ids: list[str] = Field(default_factory=list)
    protein_group_ids: list[str] = Field(default_factory=list)
    modification_ids: list[str] = Field(default_factory=list)
    quantification_ids: list[str] = Field(default_factory=list)
    source_fields: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _spectrum_link_is_truthful(self) -> "SemanticIdentification":
        if self.spectrum_link_state in {"DIRECT", "DERIVED"} and not self.spectrum_id:
            raise ValueError("a linked identification requires spectrum_id")
        if self.spectrum_link_state in {"MISSING", "AMBIGUOUS", "VIEWER_UNSUPPORTED"} and self.spectrum_id:
            raise ValueError("an unavailable spectrum link cannot contain spectrum_id")
        if self.spectrum_link_state == "DERIVED" and not self.spectrum_link_derivation_id:
            raise ValueError("a DERIVED spectrum link requires spectrum_link_derivation_id")
        if self.spectrum_link_state != "DERIVED" and self.spectrum_link_derivation_id is not None:
            raise ValueError("spectrum_link_derivation_id is allowed only for DERIVED links")
        return self


class SemanticPeptide(_StrictModel):
    peptide_id: str
    sequence: str = Field(..., min_length=1)
    identification_ids: list[str] = Field(default_factory=list)
    protein_ids: list[str] = Field(default_factory=list)
    modified_sequences: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticProtein(_StrictModel):
    protein_id: str
    accession: str = Field(..., min_length=1)
    name: str | None = None
    gene: str | None = None
    description: str | None = None
    sequence: str | None = None
    sequence_state: FactState = "MISSING"
    sequence_derivation_id: str | None = None
    is_decoy: bool | None = None
    peptide_ids: list[str] = Field(default_factory=list)
    identification_ids: list[str] = Field(default_factory=list)
    protein_group_ids: list[str] = Field(default_factory=list)
    source_fields: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sequence_state_is_truthful(self) -> "SemanticProtein":
        if self.sequence_state in {"DIRECT", "DERIVED"} and not self.sequence:
            raise ValueError("available protein sequence state requires sequence")
        if self.sequence_state in {"MISSING", "AMBIGUOUS", "VIEWER_UNSUPPORTED"} and self.sequence:
            raise ValueError("unavailable protein sequence state cannot contain sequence")
        if self.sequence_state == "DERIVED" and not self.sequence_derivation_id:
            raise ValueError("a DERIVED protein sequence requires sequence_derivation_id")
        if self.sequence_state != "DERIVED" and self.sequence_derivation_id is not None:
            raise ValueError("sequence_derivation_id is allowed only for DERIVED sequences")
        return self


class SemanticProteinGroup(_StrictModel):
    protein_group_id: str
    source_group: str
    member_protein_ids: list[str] = Field(default_factory=list)
    leading_protein_id: str | None = None
    identification_ids: list[str] = Field(default_factory=list)
    q_value: float | None = Field(default=None, ge=0, le=1)
    pep: float | None = Field(default=None, ge=0, le=1)
    source_fields: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticModification(_StrictModel):
    modification_id: str
    identification_id: str
    peptide_id: str
    name: str
    accession: str | None = None
    mass_shift: float | None = None
    position: int | None = Field(default=None, ge=0)
    residue: str | None = None
    localization_probability: float | None = Field(default=None, ge=0, le=1)
    localization_state: FactState
    localization_derivation_id: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _localization_derivation_is_truthful(self) -> "SemanticModification":
        if self.localization_state == "DERIVED" and not self.localization_derivation_id:
            raise ValueError("DERIVED localization requires localization_derivation_id")
        if self.localization_state != "DERIVED" and self.localization_derivation_id is not None:
            raise ValueError("localization_derivation_id is allowed only for DERIVED localization")
        return self


class SemanticQuantification(_StrictModel):
    quantification_id: str
    entity_kind: Literal["identification"]
    entity_id: str
    run_id: str | None = None
    sample: str | None = None
    channel: str | None = None
    value: float | None = None
    unit: str | None = None
    normalization_kind: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticRelationship(_StrictModel):
    relationship_id: str
    kind: Literal[
        "identification_to_spectrum",
        "identification_to_peptide",
        "identification_to_protein",
        "identification_to_protein_group",
        "peptide_to_protein",
        "protein_to_protein_group",
    ]
    left_id: str
    right_id: str | None = None
    state: FactState
    derivation_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _relationship_is_truthful(self) -> "SemanticRelationship":
        if self.state in {"DIRECT", "DERIVED"} and not self.right_id:
            raise ValueError("available relationship requires right_id")
        if self.state in {"MISSING", "AMBIGUOUS", "VIEWER_UNSUPPORTED"} and self.right_id:
            raise ValueError("unavailable relationship cannot contain right_id")
        if self.state == "DERIVED" and not self.derivation_id:
            raise ValueError("a DERIVED relationship requires derivation_id")
        if self.state != "DERIVED" and self.derivation_id is not None:
            raise ValueError("derivation_id is allowed only for DERIVED relationships")
        return self


class SemanticDataset(_StrictModel):
    schema_version: Literal[1] = 1
    plan_id: str
    plan_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    source_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    analysis_mode: Literal["BOTTOM_UP"] = "BOTTOM_UP"
    core_spectrum_count: int = Field(default=0, ge=0)
    core_chromatogram_count: int = Field(default=0, ge=0)
    source_files: list[SemanticSourceFile]
    asset_dispositions: list[SemanticAssetDisposition] = Field(default_factory=list)
    runs: list[SemanticRun] = Field(default_factory=list)
    identifications: list[SemanticIdentification] = Field(default_factory=list)
    peptides: list[SemanticPeptide] = Field(default_factory=list)
    proteins: list[SemanticProtein] = Field(default_factory=list)
    protein_groups: list[SemanticProteinGroup] = Field(default_factory=list)
    modifications: list[SemanticModification] = Field(default_factory=list)
    quantification: list[SemanticQuantification] = Field(default_factory=list)
    relationships: list[SemanticRelationship] = Field(default_factory=list)
    requested_view_ids: list[str] = Field(default_factory=list)
    unmapped_fields: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def semantic_extension_payload(dataset: SemanticDataset) -> dict[str, Any]:
    return {
        "owner": "viewer",
        "schema_name": SEMANTIC_EXTENSION_TYPE,
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "record_count": 1,
        "dataset": dataset.model_dump(mode="json"),
    }


def parse_semantic_extension_payload(payload: object) -> SemanticDataset:
    if not isinstance(payload, dict):
        raise ValueError("semantic extension payload must be an object")
    if (
        payload.get("owner") != "viewer"
        or payload.get("schema_name") != SEMANTIC_EXTENSION_TYPE
        or payload.get("schema_version") != SEMANTIC_SCHEMA_VERSION
        or payload.get("record_count") != 1
    ):
        raise ValueError("semantic extension identity is invalid")
    dataset = SemanticDataset.model_validate(payload.get("dataset"))
    from app.dataset_capabilities import VIEWER_VIEW_CATALOG

    incompatible = [
        view_id
        for view_id in dataset.requested_view_ids
        if (spec := VIEWER_VIEW_CATALOG.get(view_id)) is not None
        and dataset.analysis_mode not in spec.analysis_modes
    ]
    if incompatible:
        raise ValueError(
            "semantic dataset requests views incompatible with its analysis mode: "
            + ", ".join(sorted(incompatible))
        )
    return dataset
