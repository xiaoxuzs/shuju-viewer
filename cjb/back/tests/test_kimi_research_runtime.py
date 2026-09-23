from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent_import.kimi_research_runtime import DEFAULT_FORMULA_URIS, KimiResearchRuntime


def _blueprint() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_family": "agent-designed-family",
        "source_profile": "agent-designed-profile-v1",
        "analysis_category": "BOTTOM_UP",
        "executive_summary": "The dataset contains spectra and identification tables.",
        "source_assets": [
            {
                "relative_path": "sample.txt",
                "role": "identification_table",
                "media_type": "text/tab-separated-values",
                "content_summary": "One bounded table inspected locally.",
                "required_for_default_import": True,
                "evidence_ids": ["local-tree"],
                "details": {},
            }
        ],
        "scientific_entities": [
            {
                "entity_name": "identification",
                "scientific_level": "evidence",
                "description": "A detected entity.",
                "source_fields": ["sample.txt:id"],
                "identifiers": ["id"],
                "relationships": [],
                "evidence_ids": ["local-tree"],
                "details": {},
            }
        ],
        "binary_content": [
            {
                "logical_section": "extensions",
                "content": "Preserve inspected identification facts.",
                "source_assets": ["sample.txt"],
                "required": True,
                "loss_policy": "Do not silently drop fields.",
                "evidence_ids": ["local-tree"],
                "details": {},
            }
        ],
        "visualizations": [
            {
                "view_id": "overview",
                "title": "Overview",
                "purpose": "Show supported evidence.",
                "entities": ["identification"],
                "visual_components": ["count card"],
                "interactions": [],
                "prerequisites": [],
                "limitations": [],
                "evidence_ids": ["official-source"],
                "details": {},
            }
        ],
        "default_import": {
            "profile_name": "Agent profile",
            "match_rules": ["sample.txt is present"],
            "required_assets": ["sample.txt"],
            "optional_assets": [],
            "variability_rules": [],
            "editable_fields": ["display name"],
            "unsafe_automatic_assumptions": [],
        },
        "evidence": [
            {
                "evidence_id": "local-tree",
                "kind": "local_tool",
                "reference": "inspect_source_file",
                "fact": "sample.txt is present and was inspected generically.",
            },
            {
                "evidence_id": "official-source",
                "kind": "web_source",
                "reference": "https://example.org/official",
                "fact": "An authoritative source was opened.",
            },
        ],
        "gaps": [],
        "citations": [
            {
                "title": "Official source",
                "url": "https://example.org/official",
                "supports": ["overview"],
            }
        ],
        "acceptance_criteria": ["All required assets are represented."],
        "assumptions": [],
    }


def _offline_blueprint() -> dict[str, Any]:
    blueprint = _blueprint()
    blueprint["visualizations"][0]["evidence_ids"] = ["local-tree"]
    blueprint["evidence"] = [blueprint["evidence"][0]]
    blueprint["citations"] = []
    return blueprint


class FakeTransport:
    def __init__(self) -> None:
        self.chat_round = 0
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
        timeout: int,
    ) -> dict[str, Any]:
        self.requests.append((method, path, body))
        if method == "GET" and path.endswith("web-search:latest/tools"):
            return {"tools": [_tool("web_search", {"query": {"type": "string"}}, ["query"])]}
        if method == "GET" and path.endswith("fetch:latest/tools"):
            return {"tools": [_tool("fetch", {"url": {"type": "string"}}, ["url"])]}
        if path.endswith("web-search:latest/fibers"):
            return {
                "id": "fiber-search",
                "status": "succeeded",
                "context": {"encrypted_output": "encrypted-search-result"},
            }
        if path.endswith("fetch:latest/fibers"):
            return {
                "id": "fiber-fetch",
                "status": "succeeded",
                "context": {"output": "official page content"},
            }
        if path == "/chat/completions":
            self.chat_round += 1
            if self.chat_round == 1:
                return _tool_response_many(
                    [
                        ("local-1", "list_source_inventory", {"limit": 100}),
                        (
                            "local-2",
                            "inspect_source_file",
                            {"relative_path": "sample.txt"},
                        ),
                        ("local-3", "inspect_viewer_capabilities", {}),
                    ],
                    reasoning="I need local evidence first.",
                )
            if self.chat_round == 2:
                return _tool_response(
                    "web-1",
                    "web_search",
                    {"query": "official scientific visualization guidance"},
                    reasoning="Now I need current official sources.",
                )
            if self.chat_round == 3:
                return _tool_response(
                    "fetch-1",
                    "fetch",
                    {"url": "https://example.org/official"},
                    reasoning="I need to open the authoritative page.",
                )
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "The evidence is sufficient.",
                            "content": json.dumps(_blueprint()),
                        },
                    }
                ]
            }
        raise AssertionError(f"unexpected request: {method} {path}")


class LocalOnlyTransport:
    def __init__(self) -> None:
        self.chat_round = 0
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
        timeout: int,
    ) -> dict[str, Any]:
        self.requests.append((method, path, body))
        if method != "POST" or path != "/chat/completions":
            raise AssertionError(f"unexpected request: {method} {path}")
        self.chat_round += 1
        if self.chat_round == 1:
            return _tool_response_many(
                [
                    ("local-1", "list_source_inventory", {"limit": 100}),
                    (
                        "local-2",
                        "inspect_source_file",
                        {"relative_path": "sample.txt"},
                    ),
                    ("local-3", "inspect_viewer_capabilities", {}),
                ],
                reasoning="I need local evidence.",
            )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(_offline_blueprint()),
                    },
                }
            ]
        }


class PagedInventoryTransport:
    def __init__(self) -> None:
        self.chat_round = 0
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
        timeout: int,
    ) -> dict[str, Any]:
        del timeout
        self.requests.append((method, path, body))
        if method != "POST" or path != "/chat/completions" or body is None:
            raise AssertionError(f"unexpected request: {method} {path}")
        self.chat_round += 1
        if self.chat_round == 1:
            return _tool_response_many(
                [
                    ("inventory-1", "list_source_inventory", {"cursor": "", "limit": 1}),
                    ("inspect-text", "inspect_source_file", {"relative_path": "sample.txt"}),
                    ("capabilities", "inspect_viewer_capabilities", {}),
                ],
                reasoning="Start the bounded inventory and inspect one source type.",
            )
        if self.chat_round == 2:
            messages = body["messages"]
            inventory_result = next(
                json.loads(item["content"])
                for item in reversed(messages)
                if item.get("role") == "tool" and item.get("name") == "list_source_inventory"
            )
            return _tool_response_many(
                [
                    (
                        "inventory-2",
                        "list_source_inventory",
                        {"limit": 1, "cursor": inventory_result["next_cursor"]},
                    ),
                    ("inspect-json", "inspect_source_file", {"relative_path": "sample.json"}),
                ],
                reasoning="Finish inventory pagination and inspect the remaining source type.",
            )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(_offline_blueprint())},
                }
            ]
        }


def _tool(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _tool_response(
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    *,
    reasoning: str,
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": reasoning,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ]
    }


def _tool_response_many(
    calls: list[tuple[str, str, dict[str, Any]]],
    *,
    reasoning: str,
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": reasoning,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                        for call_id, name, arguments in calls
                    ],
                },
            }
        ]
    }


def test_kimi_runtime_runs_local_search_fetch_loop_and_preserves_reasoning(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("id\n1\n", encoding="utf-8")
    transport = FakeTransport()
    runtime = KimiResearchRuntime(
        base_url="https://api.moonshot.cn/v1",
        api_key="test-key",
        model="kimi-k3",
        timeout=1,
        transport=transport,
        formula_uris=DEFAULT_FORMULA_URIS,
    )

    result = runtime.run(
        source_root=str(tmp_path),
        case_id="case-1",
        analysis_category="BOTTOM_UP",
        requested_source_profile="unknown",
        format_details=None,
        user_messages=[],
        source_manifest={
            "schema_version": 1,
            "file_count": 1,
            "truncated": False,
            "files": [{"relative_path": "sample.txt", "size_bytes": 5, "suffix": ".txt"}],
            "samples": [{"content": "must not be sent"}],
        },
        zp_capabilities={"writer": "Viewer ZpWriter", "mapping_adapters": {}},
    )

    assert result.blueprint.dataset_family == "agent-designed-family"
    assert result.local_tool_calls == 3
    assert result.web_search_calls == 1
    assert result.fetch_calls == 1
    assert len(result.observations) == 3
    assert all(item.result_sha256 for item in result.observations)
    assert result.observations[0].payload
    assert [item.tool_name for item in result.trace] == [
        "list_source_inventory",
        "inspect_source_file",
        "inspect_viewer_capabilities",
        "web_search",
        "fetch",
    ]
    chat_bodies = [body for method, path, body in transport.requests if path == "/chat/completions"]
    assert all(body["tool_choice"] == "required" for body in chat_bodies[:-1])
    assert chat_bodies[-1]["tool_choice"] == "none"
    second_messages = chat_bodies[1]["messages"]
    assert any(item.get("reasoning_content") == "I need local evidence first." for item in second_messages)
    initial_user = chat_bodies[0]["messages"][1]["content"]
    assert "must not be sent" not in initial_user
    assert "test-key" not in json.dumps(result.model_dump(mode="json"))


def test_local_openai_runtime_uses_only_local_tools_and_allows_no_citations(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("id\n1\n", encoding="utf-8")
    transport = LocalOnlyTransport()
    runtime = KimiResearchRuntime(
        base_url="http://localhost:60049/v1",
        api_key="test-key",
        model="gpt-5.6-sol",
        timeout=1,
        transport=transport,
    )

    result = runtime.run(
        source_root=str(tmp_path),
        case_id="case-local-sol",
        analysis_category="BOTTOM_UP",
        requested_source_profile="unknown",
        format_details=None,
        user_messages=[],
        source_manifest={
            "schema_version": 1,
            "file_count": 1,
            "truncated": False,
            "files": [{"relative_path": "sample.txt", "size_bytes": 5, "suffix": ".txt"}],
        },
        zp_capabilities={"writer": "Viewer ZpWriter", "mapping_adapters": {}},
    )

    assert result.provider == "openai-compatible"
    assert result.model == "gpt-5.6-sol"
    assert result.local_tool_calls == 3
    assert result.web_search_calls == 0
    assert result.fetch_calls == 0
    assert len(result.observations) == 3
    assert all(item.result_sha256 for item in result.observations)
    assert result.blueprint.citations == []
    assert all(path == "/chat/completions" for _, path, _ in transport.requests)
    first_body = transport.requests[0][2]
    assert first_body is not None
    tool_names = {item["function"]["name"] for item in first_body["tools"]}
    assert "web_search" not in tool_names
    assert "fetch" not in tool_names


def test_runtime_requires_complete_inventory_and_one_generic_inspection_per_source_type(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.json").write_text('{"id": 1}', encoding="utf-8")
    (tmp_path / "sample.txt").write_text("id\n1\n", encoding="utf-8")
    transport = PagedInventoryTransport()
    runtime = KimiResearchRuntime(
        base_url="http://localhost:60049/v1",
        api_key="test-key",
        model="gpt-5.6-sol",
        timeout=1,
        transport=transport,
    )

    result = runtime.run(
        source_root=str(tmp_path),
        case_id="case-paged-inventory",
        analysis_category="BOTTOM_UP",
        requested_source_profile="unknown",
        format_details=None,
        user_messages=[],
        source_manifest={
            "schema_version": 1,
            "file_count": 2,
            "truncated": False,
            "files": [
                {"relative_path": "sample.json", "size_bytes": 9, "suffix": ".json"},
                {"relative_path": "sample.txt", "size_bytes": 5, "suffix": ".txt"},
            ],
        },
        zp_capabilities={"writer": "Viewer ZpWriter", "mapping_adapters": {}},
    )

    assert result.local_tool_calls == 5
    assert [item.tool_name for item in result.trace].count("list_source_inventory") == 2
    chat_bodies = [body for _method, path, body in transport.requests if path == "/chat/completions"]
    assert chat_bodies[1] is not None
    assert any(
        "complete paginated source inventory" in str(item.get("content"))
        for item in chat_bodies[1]["messages"]
        if isinstance(item, dict)
    )
    assert any(
        "generic inspection for source file sample.json" in str(item.get("content"))
        for item in chat_bodies[1]["messages"]
        if isinstance(item, dict)
    )
    assert chat_bodies[-1]["tool_choice"] == "none"
