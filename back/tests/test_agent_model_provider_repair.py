from __future__ import annotations

from pathlib import Path

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
