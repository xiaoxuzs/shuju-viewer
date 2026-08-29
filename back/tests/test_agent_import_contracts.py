from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent_import.contracts import AgentCandidatePlan


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


def test_candidate_plan_accepts_only_the_two_whitelisted_binary_operations() -> None:
    plan = AgentCandidatePlan.model_validate(_candidate())

    assert plan.binary_operation == "register_existing_zp"

    with pytest.raises(ValidationError):
        AgentCandidatePlan.model_validate(_candidate(binary_operation="run_shell"))


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

