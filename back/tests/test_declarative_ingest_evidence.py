from __future__ import annotations

from pathlib import Path

import pytest

from app.declarative_ingest import DeclarativeImportPlan, preflight_declarative_plan
from app.declarative_ingest.preflight import DeclarativePlanError


def test_companion_virtual_fields_are_not_tabular_field_mapping_inputs(tmp_path):
    payload = _plan(include_mzml=True).model_dump(mode="json")
    payload["field_mappings"].append({"mapping_id": "virtual-native", "source_id": "spectra", "source_field": "native_id",
        "target_entity": "spectrum", "target_field": "native_id", "value_kind": "string", "evidence_refs": ["obs:table"]})
    with pytest.raises(DeclarativePlanError, match="companion is ingested automatically"):
        preflight_declarative_plan(source_root=tmp_path, plan=DeclarativeImportPlan.model_validate(payload))


def test_registered_associations_cannot_be_replaced_by_raw_field_preservation():
    from app.declarative_ingest.preflight import _validate_evidence_bindings
    plan = DeclarativeImportPlan.model_validate({"schema_version": 1, "plan_id": "association", "analysis_mode": "BOTTOM_UP",
        "sources": [{"source_id": "rows", "relative_path": "renamed.tsv", "role": "entity_rows", "reader": "delimited", "delimiter": "\t"}],
        "field_mappings": [{"mapping_id": "value", "source_id": "rows", "source_field": "Intensity", "target_entity": "quantification",
            "target_field": "value", "value_kind": "float", "unit": "source_intensity", "evidence_refs": ["observed"]}],
        "unmapped_fields": {"rows": ["Proteins", "Experiment"]}})
    observation = {"relative_path": "renamed.tsv", "facts": {"profile": "maxquant-reported-table-v1",
        "fields": [{"name": name} for name in ("Intensity", "Proteins", "Experiment")],
        "required_field_targets": {"Proteins": "identification.protein_accessions", "Experiment": "quantification.sample"}}}
    with pytest.raises(DeclarativePlanError, match="registered source semantics require"):
        _validate_evidence_bindings(plan, {"observed": observation})


def test_registered_unlabelled_source_cannot_invent_channel_from_metric_name():
    from app.declarative_ingest.preflight import _validate_evidence_bindings
    payload = {"schema_version": 1, "plan_id": "channel-negative", "analysis_mode": "BOTTOM_UP",
        "sources": [{"source_id": "source", "relative_path": "source.parquet", "role": "identifications", "reader": "parquet"}],
        "field_mappings": [{"mapping_id": "value", "source_id": "source", "source_field": "DIAClip.Quantity",
            "target_entity": "quantification", "target_field": "value", "value_kind": "float",
            "measurement_name": "DIAClip.Quantity", "unit": "source_intensity", "evidence_refs": ["observed"]}]}
    plan = DeclarativeImportPlan.model_validate(payload)
    observation = {"relative_path": "source.parquet", "facts": {"profile": "diaclip-fdr-reader-v1", "labelled_channels": False,
        "fields": [{"name": "DIAClip.Quantity"}]}}
    with pytest.raises(DeclarativePlanError, match="no labelled channel"):
        _validate_evidence_bindings(plan, {"observed": observation})
    payload["field_mappings"][0].pop("measurement_name")
    _validate_evidence_bindings(DeclarativeImportPlan.model_validate(payload), {"observed": observation})


def test_agent_schema_exposes_conditional_mzml_acquisition_requirements() -> None:
    from app.agent_import.contracts import AgentCandidatePlan
    from app.declarative_ingest import build_declarative_ingest_capabilities

    schema = AgentCandidatePlan.model_json_schema()["$defs"]["DeclarativeImportPlan"]
    condition = schema["allOf"][0]
    assert condition["if"]["properties"]["sources"]["contains"]["properties"]["reader"] == {"const": "mzml"}
    assert condition["then"]["required"] == ["acquisition_mode", "acquisition_mode_evidence_refs"]
    assert condition["then"]["properties"]["acquisition_mode"]["enum"] == ["dda", "dia"]
    assert condition["then"]["properties"]["acquisition_mode_evidence_refs"]["minItems"] == 1
    assert any("acquisition_mode_evidence_refs" in rule for rule in build_declarative_ingest_capabilities()["rules"])


def _plan(*, include_mzml: bool = False, include_fasta: bool = False) -> DeclarativeImportPlan:
    sources: list[dict[str, object]] = [
        {
            "source_id": "ids",
            "relative_path": "results.tsv",
            "role": "identifications",
            "reader": "delimited",
            "delimiter": "\t",
            "required": True,
            "required_fields": ["id", "run", "sequence", "rt"],
        }
    ]
    if include_mzml:
        sources.append(
            {
                "source_id": "spectra",
                "relative_path": "run.mzML",
                "role": "spectra",
                "reader": "mzml",
                "required": False,
            }
        )
    if include_fasta:
        sources.append(
            {
                "source_id": "fasta",
                "relative_path": "search.fasta",
                "role": "reference_sequences",
                "reader": "fasta",
                "required": False,
                "fasta_accession_rule": "uniprot_pipe_accession",
                "accession_rule_evidence_refs": ["obs:fasta"],
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "plan_id": "evidence-contract-v1",
        "analysis_mode": "BOTTOM_UP",
        "sources": sources,
        "field_mappings": [
            {
                "mapping_id": "id",
                "source_id": "ids",
                "source_field": "id",
                "target_entity": "identification",
                "target_field": "source_id",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "run",
                "source_id": "ids",
                "source_field": "run",
                "target_entity": "run",
                "target_field": "name",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "sequence",
                "source_id": "ids",
                "source_field": "sequence",
                "target_entity": "peptide",
                "target_field": "sequence",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "rt",
                "source_id": "ids",
                "source_field": "rt",
                "target_entity": "identification",
                "target_field": "rt_seconds",
                "value_kind": "float",
                "unit": "minute",
                "transform": "minute_to_second",
                "evidence_refs": ["obs:table", "user-message:1"],
            },
        ],
        "unmapped_fields": {"ids": []},
    }
    if include_mzml:
        payload["acquisition_mode"] = "dda"
        payload["acquisition_mode_evidence_refs"] = ["user-message:2"]
    return DeclarativeImportPlan.model_validate(payload)


def _write_sources(root: Path, *, include_mzml: bool = False, include_fasta: bool = False) -> None:
    (root / "results.tsv").write_text(
        "id\trun\tsequence\trt\n1\trun-a\tPEPTIDE\t1.5\n",
        encoding="utf-8",
    )
    if include_mzml:
        (root / "run.mzML").write_text("<mzML/>", encoding="utf-8")
    if include_fasta:
        (root / "search.fasta").write_text(">sp|P42|PROTEIN\nPEPTIDE\n", encoding="utf-8")


def _observations(*, unit_message: str, acquisition_message: str | None = None) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {
        "obs:table": {
            "relative_path": "results.tsv",
            "facts": {"columns": [{"name": name} for name in ("id", "run", "sequence", "rt")]},
        },
        "user-message:1": {"kind": "user_input", "text": unit_message},
    }
    if acquisition_message is not None:
        result["user-message:2"] = {"kind": "user_input", "text": acquisition_message}
    return result


def test_exact_user_confirmations_can_resolve_unit_and_acquisition_mode(tmp_path: Path) -> None:
    _write_sources(tmp_path, include_mzml=True)
    report = preflight_declarative_plan(
        source_root=tmp_path,
        plan=_plan(include_mzml=True),
        trusted_observations=_observations(
            unit_message="confirm unit:rt=minute",
            acquisition_message="confirm acquisition_mode=dda",
        ),
    )

    assert report.status == "PASSED"


@pytest.mark.parametrize(
    ("unit_message", "acquisition_message", "expected_code"),
    [
        ("RT is probably minutes", "confirm acquisition_mode=dda", "UNIT_AMBIGUOUS"),
        ("confirm unit:rt=minute", "This looks like DDA", "SCIENTIFIC_SEMANTIC_UNKNOWN"),
    ],
)
def test_free_form_prose_is_not_treated_as_scientific_confirmation(
    tmp_path: Path,
    unit_message: str,
    acquisition_message: str,
    expected_code: str,
) -> None:
    _write_sources(tmp_path, include_mzml=True)

    with pytest.raises(DeclarativePlanError) as exc_info:
        preflight_declarative_plan(
            source_root=tmp_path,
            plan=_plan(include_mzml=True),
            trusted_observations=_observations(
                unit_message=unit_message,
                acquisition_message=acquisition_message,
            ),
        )

    assert exc_info.value.code == expected_code


def test_uniprot_fasta_accession_rule_requires_matching_header_evidence(tmp_path: Path) -> None:
    _write_sources(tmp_path, include_fasta=True)
    observations = _observations(unit_message="confirm unit:rt=minute")
    observations["obs:fasta"] = {
        "relative_path": "search.fasta",
        "facts": {"identifier_samples": ["sp|P42|PROTEIN", "tr|Q7|PROTEIN_2"]},
    }

    assert preflight_declarative_plan(
        source_root=tmp_path,
        plan=_plan(include_fasta=True),
        trusted_observations=observations,
    ).status == "PASSED"

    observations["obs:fasta"] = {
        "relative_path": "search.fasta",
        "facts": {"identifier_samples": ["P42"]},
    }
    with pytest.raises(DeclarativePlanError, match="lacks evidence") as exc_info:
        preflight_declarative_plan(
            source_root=tmp_path,
            plan=_plan(include_fasta=True),
            trusted_observations=observations,
        )
    assert exc_info.value.code == "SCIENTIFIC_SEMANTIC_UNKNOWN"


def test_asset_disposition_requires_an_observation_for_that_exact_file(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    (tmp_path / "opaque.bin").write_bytes(b"opaque")
    payload = _plan().model_dump(mode="json")
    payload["asset_dispositions"] = [
        {
            "relative_path": "opaque.bin",
            "disposition": "UNSUPPORTED",
            "reason": "No trusted reader is registered for this payload.",
            "evidence_refs": ["obs:other"],
        }
    ]
    plan = DeclarativeImportPlan.model_validate(payload)
    observations = _observations(unit_message="confirm unit:rt=minute")
    observations["obs:other"] = {"relative_path": "results.tsv", "facts": {}}

    with pytest.raises(DeclarativePlanError, match="path-specific observation") as exc_info:
        preflight_declarative_plan(
            source_root=tmp_path,
            plan=plan,
            trusted_observations=observations,
        )
    assert exc_info.value.code == "SCIENTIFIC_SEMANTIC_UNKNOWN"

    observations["obs:other"] = {"relative_path": "opaque.bin", "facts": {}}
    assert preflight_declarative_plan(
        source_root=tmp_path,
        plan=plan,
        trusted_observations=observations,
    ).status == "PASSED"
