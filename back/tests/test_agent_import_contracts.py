from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.model_provider import _normalize_candidate_protocol
from app.agent_import.research_contracts import DatasetBlueprint


def _candidate(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "analysis_category": "SPECTRA_ONLY",
        "source_profile": "existing-zp-package",
        "binary_operation": "register_existing_zp",
        "zp_conversion_plan": {
            "relative_source": "candidate.zp",
            "target_format_version": 3,
        },
    }
    payload.update(overrides)
    return payload


def test_candidate_plan_accepts_only_whitelisted_binary_operations() -> None:
    plan = AgentCandidatePlan.model_validate(_candidate())

    assert plan.binary_operation == "register_existing_zp"

    with pytest.raises(ValidationError):
        AgentCandidatePlan.model_validate(_candidate(binary_operation="run_shell"))


def test_non_ready_candidate_requires_questions_and_cannot_execute() -> None:
    plan = AgentCandidatePlan.model_validate(
        {
            "schema_version": 2,
            "status": "NEEDS_USER",
            "analysis_category": "BOTTOM_UP",
            "source_profile": "tabular_profile_v1",
            "questions": ["Which analysis category should be used?"],
        }
    )

    assert plan.binary_operation is None
    assert plan.zp_conversion_plan is None

    with pytest.raises(ValidationError):
        AgentCandidatePlan.model_validate(
            {
                **plan.model_dump(mode="json"),
                "binary_operation": "convert_declared_mapping_to_zp",
            }
        )


def test_agent_two_candidate_preserves_custom_analysis_category() -> None:
    plan = AgentCandidatePlan.model_validate(
        _candidate(analysis_category="DIA-CLIP quantitative imaging")
    )

    assert plan.analysis_category == "DIA-CLIP quantitative imaging"


def test_agent_one_blueprint_schema_accepts_custom_analysis_category() -> None:
    schema = DatasetBlueprint.model_json_schema()["properties"]["analysis_category"]

    assert schema["maxLength"] == 80
    assert "enum" not in schema


def test_declared_mapping_protocol_is_normalized_to_schema_version_two() -> None:
    payload = {
        "schema_version": 1,
        "binary_operation": "convert_declared_mapping_to_zp",
        "zp_conversion_plan": {"mapping_plan": {"adapter_id": "agent-defined"}},
    }

    normalized = _normalize_candidate_protocol(payload)

    assert normalized["schema_version"] == 2
    assert payload["schema_version"] == 1


@pytest.mark.parametrize("relative_source", ["../outside.zp", "/outside.zp", "C:/outside.zp"])
def test_candidate_plan_rejects_sources_outside_the_case_root(relative_source: str) -> None:
    payload = _candidate()
    payload["zp_conversion_plan"] = {
        "relative_source": relative_source,
        "target_format_version": 3,
    }

    with pytest.raises(ValidationError):
        AgentCandidatePlan.model_validate(payload)


def test_register_existing_zp_requires_a_zp_relative_source() -> None:
    payload = _candidate()
    payload["zp_conversion_plan"] = {
        "relative_source": "candidate.mzML",
        "target_format_version": 3,
    }

    with pytest.raises(ValidationError):
        AgentCandidatePlan.model_validate(payload)
