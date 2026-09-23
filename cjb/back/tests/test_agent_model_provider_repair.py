from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_import.errors import AgentImportError
from app.agent_import.model_provider import (
    AgentModelContext,
    ConfiguredAgentModelProvider,
)


def test_deepseek_candidate_schema_failure_is_returned_as_serializable_repair_feedback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.agent_import import model_provider

    responses = [
        {
            "schema_version": 2,
            "status": "READY",
            "analysis_category": "BOTTOM_UP",
            "source_profile": "broken",
        },
        {
            "schema_version": 2,
            "status": "UNSUPPORTED",
            "analysis_category": "BOTTOM_UP",
            "source_profile": "repaired-safe-decision",
            "questions": ["A controlled adapter is unavailable."],
        },
    ]
    calls: list[dict[str, object]] = []

    def fake_chat_json(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(model_provider, "_chat_json", fake_chat_json)
    monkeypatch.setattr(model_provider.settings, "deepseek_api_key", "test-key")
    context = AgentModelContext(
        case_id="case-repair",
        context_revision=1,
        source_root=str(tmp_path),
        analysis_category="BOTTOM_UP",
        requested_source_profile="unknown",
        format_details=None,
        dataset_fingerprint="0" * 32,
        source_summary={"schema_version": 1, "file_count": 0, "files": []},
        user_messages=[],
    )

    candidate = ConfiguredAgentModelProvider().build_candidate(
        context,
        {"blueprint": {"source_profile": "unknown"}},
    )

    assert candidate.status == "UNSUPPORTED"
    assert len(calls) == 2
    feedback = calls[1]["payload"]["repair_feedback"]
    assert feedback["kind"] == "candidate_schema_rejected"
    assert isinstance(feedback["errors"], str)
    assert "validation error" in feedback["errors"]


def test_model_transport_failure_is_classified_as_infrastructure(tmp_path: Path, monkeypatch) -> None:
    from app.agent_import import model_provider

    monkeypatch.setattr(
        model_provider,
        "_chat_json",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("provider timeout")),
    )
    monkeypatch.setattr(model_provider.settings, "deepseek_api_key", "test-key")
    context = AgentModelContext(
        case_id="case-timeout",
        context_revision=1,
        source_root=str(tmp_path),
        analysis_category="BOTTOM_UP",
        requested_source_profile="unknown",
        format_details=None,
        dataset_fingerprint="0" * 32,
        source_summary={"schema_version": 1, "file_count": 0, "files": []},
        user_messages=[],
    )

    with pytest.raises(AgentImportError) as exc_info:
        ConfiguredAgentModelProvider().build_candidate(context, {"blueprint": {}})

    assert exc_info.value.code == "MODEL_PROVIDER_UNAVAILABLE"


def test_every_rejected_candidate_has_redacted_field_diagnostics(tmp_path: Path, monkeypatch) -> None:
    from app.agent_import import model_provider

    records = []
    requests = []
    def fake_chat(**kwargs):
        requests.append(kwargs["payload"])
        assert len(records) == len(requests) - 1
        return {"status": "READY", "analysis_category": "BOTTOM_UP", "source_profile": "unknown",
                "unexpected": {"api_key": "private-key", "path": "E:/private/dataset.tsv"}}

    monkeypatch.setattr(model_provider, "_chat_json", fake_chat)
    monkeypatch.setattr(model_provider.settings, "deepseek_api_key", "private-key")
    context = AgentModelContext(
        case_id="case-invalid", context_revision=2, source_root=str(tmp_path),
        analysis_category="AUTO", requested_source_profile="unknown", format_details=None,
        dataset_fingerprint="a" * 32, source_summary={}, user_messages=[], candidate_diagnostic_sink=records.append,
    )

    with pytest.raises(AgentImportError) as failure:
        ConfiguredAgentModelProvider().build_candidate(context, {"blueprint": {}})

    assert failure.value.code == "AGENT_CANDIDATE_SCHEMA_INVALID"
    assert len(records) == len(requests) == 3
    assert [item["candidate_attempt"] for item in records] == [1, 2, 3]
    assert all(item["context_revision"] == 2 and item["errors"] for item in records)
    assert all("input" not in error and "ctx" not in error for item in records for error in item["errors"])
    assert records[0]["candidate"]["unexpected"]["api_key"] == "[REDACTED]"
    assert records[0]["candidate"]["unexpected"]["path"] == "[REDACTED_PATH]"
    assert requests[1]["repair_feedback"]["field_errors"] == records[0]["errors"]
    assert failure.value.diagnostics["errors"] == records[-1]["errors"]
    assert "candidate" not in failure.value.diagnostics


def test_successful_repair_keeps_prior_diagnostic_without_extra_calls(tmp_path: Path, monkeypatch) -> None:
    from app.agent_import import model_provider
    records = []
    replies = iter([
        {"status": "READY", "analysis_category": "BOTTOM_UP", "source_profile": "unknown"},
        {"status": "NEEDS_USER", "analysis_category": "BOTTOM_UP", "source_profile": "unknown",
         "questions": ["Confirm the retention time unit."]},
    ])
    monkeypatch.setattr(model_provider, "_chat_json", lambda **kw: next(replies))
    monkeypatch.setattr(model_provider.settings, "deepseek_api_key", "private-key")
    context = AgentModelContext(
        case_id="case-repaired", context_revision=1, source_root=str(tmp_path), analysis_category="AUTO",
        requested_source_profile="unknown", format_details=None, dataset_fingerprint="a" * 32,
        source_summary={}, user_messages=[], candidate_diagnostic_sink=records.append,
    )
    assert ConfiguredAgentModelProvider().build_candidate(context, {}).status == "NEEDS_USER"
    assert len(records) == 1
