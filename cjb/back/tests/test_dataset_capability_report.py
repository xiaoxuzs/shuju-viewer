from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import datasets as datasets_api
from app.dataset_capabilities import (
    CapabilityAmbiguity,
    CapabilityWarning,
    EntityCapability,
    FactState,
    MissingInput,
    ValidatedDatasetFacts,
    ViewAvailability,
    ViewRequirement,
    compile_capability_report,
    compile_legacy_capability_report,
    compile_semantic_capability_report,
    validate_capability_report,
)
from app.declarative_ingest.semantic_schema import SemanticDataset


def _entity(
    entity: str,
    state: FactState,
    *,
    count: int | None = None,
    reason_code: str | None = None,
    derivation_id: str | None = None,
) -> EntityCapability:
    return EntityCapability(
        entity=entity,
        state=state,
        count=count,
        reason_code=reason_code,
        evidence_refs=[f"validation:{entity}"],
        derivation_id=derivation_id,
    )


def _complete_facts() -> ValidatedDatasetFacts:
    return ValidatedDatasetFacts(
        dataset_id=41,
        source_case_id="case-41",
        entities=[
            _entity("spectra", FactState.DIRECT, count=120),
            _entity("psms", FactState.DIRECT, count=18),
            _entity("peptides", FactState.DIRECT, count=12),
            _entity("proteins", FactState.DIRECT, count=4),
            _entity("protein_sequences", FactState.MISSING, reason_code="FASTA_MISSING"),
            _entity("peptide_positions", FactState.MISSING, reason_code="FASTA_MISSING"),
            _entity(
                "chromatograms",
                FactState.DERIVED,
                count=2,
                reason_code="DERIVED_FROM_MS1",
                derivation_id="viewer.chromatogram.tic-bpc.v1",
            ),
            _entity(
                "fragment_annotations",
                FactState.MISSING,
                reason_code="FRAGMENT_ANNOTATIONS_MISSING",
            ),
            _entity("quantification", FactState.AMBIGUOUS, reason_code="QUANT_UNIT_AMBIGUOUS"),
        ],
        missing_inputs=[
            MissingInput(
                input_id="search_fasta",
                label="Search FASTA",
                reason_code="FASTA_MISSING",
                message="Provide the FASTA used by this search.",
                unlocks=["bu.protein_coverage"],
            )
        ],
        ambiguities=[
            CapabilityAmbiguity(
                ambiguity_id="quant_unit",
                message="The quantity column has no declared unit.",
                evidence_refs=["validation:quantification"],
                affected_views=["quantification"],
            )
        ],
        warnings=[
            CapabilityWarning(
                warning_id="partial_dataset",
                message="Reliable entities remain usable.",
                evidence_refs=["validation:summary"],
            )
        ],
    )


def test_contract_rejects_unknown_fields_and_derived_requirement_without_provenance() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EntityCapability.model_validate(
            {
                "entity": "spectra",
                "state": "DIRECT",
                "count": 1,
                "reason_code": None,
                "evidence_refs": [],
                "derivation_id": None,
                "invented": True,
            }
        )

    with pytest.raises(ValidationError, match="DERIVED view requirements require derivation_id"):
        ViewRequirement(
            entity="chromatograms",
            state=FactState.DERIVED,
            required=True,
        )

    with pytest.raises(ValidationError):
        ValidatedDatasetFacts.model_validate({"dataset_id": "41", "entities": []})


def test_compiler_reports_available_partial_and_disabled_views() -> None:
    report = compile_capability_report(_complete_facts())
    views = {item.view_id: item for item in report.views}

    assert report.schema_version == 1
    assert report.dataset_id == 41
    assert report.source_case_id == "case-41"
    assert views["spectra"].availability is ViewAvailability.AVAILABLE
    assert views["bu.matches"].availability is ViewAvailability.AVAILABLE
    assert views["bu.proteins"].availability is ViewAvailability.AVAILABLE
    assert views["bu.protein_coverage"].availability is ViewAvailability.DISABLED
    assert views["bu.protein_coverage"].reason_code == "REQUIRED_DATA_MISSING"
    assert views["fragment_annotation"].availability is ViewAvailability.DISABLED
    assert views["quantification"].availability is ViewAvailability.DISABLED
    assert views["quantification"].reason_code == "REQUIREMENT_AMBIGUOUS"
    chromatogram_requirement = views["chromatogram"].requirements[0]
    assert chromatogram_requirement.state is FactState.DERIVED
    assert chromatogram_requirement.derivation_id == "viewer.chromatogram.tic-bpc.v1"
    assert report.missing_inputs[0].unlocks == ["bu.protein_coverage"]


def test_compiler_does_not_treat_an_unregistered_view_as_supported() -> None:
    report = compile_capability_report(
        _complete_facts(),
        requested_view_ids=["future_network"],
    )

    view = report.views[0]
    assert view.view_id == "future_network"
    assert view.availability is ViewAvailability.DISABLED
    assert view.reason_code == "VIEWER_UNSUPPORTED"
    assert view.requirements[0].state is FactState.VIEWER_UNSUPPORTED


def test_persisted_report_view_state_must_match_verified_facts() -> None:
    payload = compile_capability_report(_complete_facts()).model_dump(mode="json")
    payload["views"][0]["availability"] = "DISABLED"

    with pytest.raises(ValueError, match="view state does not match its facts"):
        validate_capability_report(payload, expected_dataset_id=41)


def test_report_rejects_advisory_label_on_validated_facts() -> None:
    payload = compile_capability_report(_complete_facts()).model_dump(mode="json")
    payload["enforcement"] = "ADVISORY"

    with pytest.raises(ValueError, match="provenance and enforcement are inconsistent"):
        validate_capability_report(payload, expected_dataset_id=41)


def test_legacy_compiler_only_uses_explicit_capability_signals() -> None:
    report = compile_legacy_capability_report(
        dataset_id=7,
        capabilities={
            "has_spectrum_files": True,
            "has_identifications": False,
            "unrelated_future_flag": True,
        },
    )

    assert report.provenance == "LEGACY_METADATA"
    assert report.enforcement == "ADVISORY"
    entities = {item.entity: item for item in report.entities}
    views = {item.view_id: item for item in report.views}

    assert entities["spectra"].state is FactState.DIRECT
    assert entities["psms"].state is FactState.MISSING
    assert entities["proteins"].state is FactState.AMBIGUOUS
    assert entities["quantification"].state is FactState.AMBIGUOUS
    assert views["spectra"].availability is ViewAvailability.AVAILABLE
    assert views["bu.matches"].availability is ViewAvailability.DISABLED
    assert report.missing_inputs == []
    assert report.ambiguities[0].ambiguity_id == "legacy_capabilities_incomplete"
    assert report.warnings[0].warning_id == "legacy_capability_metadata"


def test_capability_report_endpoint_prefers_strictly_validated_stored_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = compile_capability_report(_complete_facts())
    row = {
        "dataset_id": 41,
        "capabilities": {"has_spectrum_files": False},
        "extra_metadata": {"dataset_capability_report": expected.model_dump(mode="json")},
    }
    monkeypatch.setattr(datasets_api, "require_dataset", lambda *_args: row)

    actual = datasets_api.get_dataset_capability_report("demo", object())  # type: ignore[arg-type]

    assert actual == expected
    assert actual.views[0].availability is ViewAvailability.AVAILABLE


def test_capability_report_endpoint_rejects_invalid_stored_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = compile_capability_report(_complete_facts()).model_dump(mode="json")
    payload["schema_version"] = 2
    row = {
        "dataset_id": 41,
        "capabilities": {"has_spectrum_files": True},
        "extra_metadata": {"dataset_capability_report": payload},
    }
    monkeypatch.setattr(datasets_api, "require_dataset", lambda *_args: row)

    with pytest.raises(HTTPException) as error:
        datasets_api.get_dataset_capability_report("demo", object())  # type: ignore[arg-type]

    assert error.value.status_code == 500
    assert error.value.detail["code"] == "INVALID_DATASET_CAPABILITY_REPORT"


def test_capability_report_endpoint_builds_conservative_legacy_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: dict[str, Any] = {
        "dataset_id": 9,
        "capabilities": {
            "has_spectrum_files": True,
            "has_identifications": False,
        },
        "extra_metadata": {"agent_zp": {"case_id": "case-9"}},
    }
    monkeypatch.setattr(datasets_api, "require_dataset", lambda *_args: row)

    report = datasets_api.get_dataset_capability_report("legacy", object())  # type: ignore[arg-type]

    assert report.dataset_id == 9
    assert report.source_case_id == "case-9"
    assert report.warnings[0].warning_id == "legacy_capability_metadata"


def test_capability_report_route_is_registered() -> None:
    paths = {route.path for route in datasets_api.router.routes}
    assert "/datasets/{slug}/capability-report" in paths


def _semantic_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plan_id": "semantic-plan-v1",
        "plan_sha256": "a" * 64,
        "source_fingerprint": "b" * 32,
        "analysis_mode": "BOTTOM_UP",
        "source_files": [
            {
                "source_id": "results",
                "relative_path": "results.tsv",
                "role": "identification_table",
                "reader": "delimited",
                "size_bytes": 120,
                "sha256": "c" * 64,
            }
        ],
        "runs": [
            {
                "run_id": "run:1",
                "name": "run-1",
                "source_file": "results",
                "evidence_refs": ["table:run"],
            }
        ],
        "identifications": [
            {
                "identification_id": "identification:1",
                "source_record_id": "row-1",
                "run_id": "run:1",
                "peptide_id": "peptide:1",
                "spectrum_id": None,
                "spectrum_link_state": "MISSING",
                "protein_ids": ["protein:1"],
                "quantification_ids": [],
                "source_fields": {"record": "row-1"},
                "evidence_refs": ["table:row-1"],
            }
        ],
        "peptides": [
            {
                "peptide_id": "peptide:1",
                "sequence": "PEPTIDE",
                "identification_ids": ["identification:1"],
                "protein_ids": ["protein:1"],
                "evidence_refs": ["table:peptide"],
            }
        ],
        "proteins": [
            {
                "protein_id": "protein:1",
                "accession": "P1",
                "sequence": None,
                "sequence_state": "MISSING",
                "peptide_ids": ["peptide:1"],
                "identification_ids": ["identification:1"],
                "evidence_refs": ["table:protein"],
            }
        ],
        "protein_groups": [],
        "modifications": [],
        "quantification": [],
        "relationships": [
            {
                "relationship_id": "relationship:1",
                "kind": "peptide_to_protein",
                "left_id": "peptide:1",
                "right_id": "protein:1",
                "state": "DIRECT",
                "evidence_refs": ["table:protein"],
            }
        ],
        "unmapped_fields": {},
        "warnings": [
            "REFERENCE_SEQUENCE_MISSING: protein accessions are available but no FASTA was supplied",
            "SPECTRUM_SOURCE_MISSING: identifications cannot open raw spectra",
            "FRAGMENT_ANNOTATION_MISSING: no fragment annotations were supplied",
        ],
    }


def test_semantic_compiler_keeps_tables_available_without_fasta_or_spectra() -> None:
    semantic = SemanticDataset.model_validate(_semantic_payload())

    report = compile_semantic_capability_report(51, "case-51", semantic)
    entities = {item.entity: item for item in report.entities}
    views = {item.view_id: item for item in report.views}

    assert entities["psms"].count == 1
    assert entities["peptides"].state is FactState.DIRECT
    assert entities["proteins"].state is FactState.DIRECT
    assert entities["proteins"].count == 1
    assert entities["protein_sequences"].state is FactState.MISSING
    assert entities["spectra"].state is FactState.MISSING
    assert entities["chromatograms"].state is FactState.MISSING
    assert entities["fragment_annotations"].state is FactState.MISSING
    assert views["bu.matches"].availability is ViewAvailability.AVAILABLE
    assert views["bu.peptides"].availability is ViewAvailability.AVAILABLE
    assert views["bu.proteins"].availability is ViewAvailability.AVAILABLE
    assert views["spectra"].availability is ViewAvailability.DISABLED
    assert views["chromatogram"].availability is ViewAvailability.DISABLED
    assert views["fragment_annotation"].availability is ViewAvailability.DISABLED
    assert views["bu.protein_coverage"].availability is ViewAvailability.DISABLED
    assert report.missing_inputs[0].input_id == "fasta"
    assert report.missing_inputs[0].unlocks == ["bu.protein_coverage"]
    assert {item.warning_id for item in report.warnings} == {
        "reference_sequence_missing",
        "spectrum_source_missing",
        "fragment_annotation_missing",
        "decoy_labels_unavailable",
    }


def test_semantic_compiler_reports_every_non_input_asset_disposition() -> None:
    payload = _semantic_payload()
    payload["asset_dispositions"] = [
        {
            "relative_path": "instrument.json",
            "disposition": "PROVENANCE_ONLY",
            "reason": "The v1 executor cannot project this metadata.",
            "evidence_refs": ["obs:instrument"],
        },
        {
            "relative_path": "opaque.bin",
            "disposition": "UNSUPPORTED",
            "reason": "No trusted reader is registered.",
            "evidence_refs": ["obs:opaque"],
        },
    ]

    report = compile_semantic_capability_report(
        51,
        "case-assets",
        SemanticDataset.model_validate(payload),
    )
    messages = {item.warning_id: item.message for item in report.warnings}

    assert messages["provenance_only_asset_1"].startswith(
        "PROVENANCE_ONLY: instrument.json"
    )
    assert messages["unsupported_asset_2"].startswith("VIEWER_UNSUPPORTED: opaque.bin")


def test_semantic_compiler_marks_partial_fasta_coverage_as_partial() -> None:
    payload = _semantic_payload()
    payload["proteins"][0]["sequence"] = "XXPEPTIDEXX"
    payload["proteins"][0]["sequence_state"] = "DIRECT"
    payload["proteins"].append(
        {
            "protein_id": "protein:2",
            "accession": "P2",
            "sequence": None,
            "sequence_state": "MISSING",
            "peptide_ids": ["peptide:2"],
            "identification_ids": ["identification:2"],
            "evidence_refs": ["table:protein-2"],
        }
    )
    payload["peptides"].append(
        {
            "peptide_id": "peptide:2",
            "sequence": "OTHER",
            "identification_ids": ["identification:2"],
            "protein_ids": ["protein:2"],
            "evidence_refs": ["table:peptide-2"],
        }
    )
    payload["identifications"].append(
        {
            "identification_id": "identification:2",
            "source_record_id": "row-2",
            "run_id": "run:1",
            "peptide_id": "peptide:2",
            "spectrum_id": None,
            "spectrum_link_state": "MISSING",
            "protein_ids": ["protein:2"],
            "quantification_ids": [],
            "source_fields": {"record": "row-2"},
            "evidence_refs": ["table:row-2"],
        }
    )
    semantic = SemanticDataset.model_validate(payload)

    report = compile_semantic_capability_report(52, "case-52", semantic)
    entities = {item.entity: item for item in report.entities}
    views = {item.view_id: item for item in report.views}

    assert entities["protein_sequences"].state is FactState.DIRECT
    assert entities["protein_sequences"].count == 1
    assert entities["peptide_positions"].state is FactState.DERIVED
    assert entities["peptide_positions"].count == 1
    assert entities["peptide_positions"].derivation_id == "viewer.peptide-position.exact-subsequence.v1"
    assert views["bu.protein_coverage"].availability is ViewAvailability.PARTIAL
    assert report.missing_inputs[0].reason_code == "FASTA_MISSING"


def test_semantic_compiler_projects_spectra_quantification_and_unknown_requested_view() -> None:
    payload = _semantic_payload()
    payload["source_files"].append(
        {
            "source_id": "spectra",
            "relative_path": "run.mzML",
            "role": "spectra",
            "reader": "mzml",
            "size_bytes": 420,
            "sha256": "d" * 64,
        }
    )
    payload["identifications"][0]["spectrum_id"] = "spectrum:1"
    payload["identifications"][0]["spectrum_link_state"] = "DIRECT"
    payload["identifications"][0]["quantification_ids"] = ["quantification:1"]
    payload["proteins"][0]["sequence"] = "XXPEPTIDEXX"
    payload["proteins"][0]["sequence_state"] = "DIRECT"
    payload["modifications"] = [
        {
            "modification_id": "modification:1",
            "identification_id": "identification:1",
            "peptide_id": "peptide:1",
            "name": "Oxidation",
            "position": 2,
            "localization_state": "DIRECT",
            "evidence_refs": ["table:modification"],
        }
    ]
    payload["quantification"] = [
        {
            "quantification_id": "quantification:1",
            "entity_kind": "identification",
            "entity_id": "identification:1",
            "run_id": "run:1",
            "value": 123.0,
            "unit": "intensity",
            "evidence_refs": ["table:quantity"],
        }
    ]
    payload["warnings"] = []
    semantic = SemanticDataset.model_validate(payload)

    report = compile_semantic_capability_report(
        53,
        "case-53",
        semantic,
        [
            "bu.matches",
            "bu.protein_coverage",
            "spectra",
            "chromatogram",
            "fragment_annotation",
            "quantification",
            "future.network",
        ],
    )
    entities = {item.entity: item for item in report.entities}
    views = {item.view_id: item for item in report.views}

    assert entities["spectra"].count == 1
    assert entities["quantification"].count == 1
    assert entities["modifications"].count == 1
    assert views["bu.matches"].availability is ViewAvailability.AVAILABLE
    assert views["bu.protein_coverage"].availability is ViewAvailability.AVAILABLE
    assert views["spectra"].availability is ViewAvailability.AVAILABLE
    assert views["chromatogram"].availability is ViewAvailability.AVAILABLE
    assert views["chromatogram"].requirements[0].derivation_id == "viewer.chromatogram.tic-bpc.v1"
    assert views["quantification"].availability is ViewAvailability.AVAILABLE
    assert views["fragment_annotation"].availability is ViewAvailability.DISABLED
    assert entities["fragment_annotations"].state is FactState.MISSING
    assert views["future.network"].availability is ViewAvailability.DISABLED
    assert views["future.network"].requirements[0].state is FactState.VIEWER_UNSUPPORTED


def test_semantic_compiler_preserves_legacy_requested_view_alias() -> None:
    semantic = SemanticDataset.model_validate(_semantic_payload())

    report = compile_semantic_capability_report(54, None, semantic, ["bu_matches"])

    assert report.views[0].view_id == "bu_matches"
    assert report.views[0].availability is ViewAvailability.AVAILABLE
