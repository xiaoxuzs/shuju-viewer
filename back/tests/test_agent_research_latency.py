import copy
import json

import pytest

from app.agent_import.model_context import compact_research_evidence, compact_schema, size
from app.agent_import.research_contracts import DatasetBlueprint
from app.agent_import.kimi_research_runtime import UrllibJsonTransport, KimiResearchError


def test_wide_preview_compacts_losslessly_without_dropping_any_of_ten_rows():
    original = {"relative_path": "any-table.tsv", "preview": {"records": [
        {"a long column name " + str(c): (None if c % 3 == 0 else 0 if c % 3 == 1 else f"row {r}") for c in range(48)}
        for r in range(10)], "preview_only": True},
        "facts": {"columns": [{"name": f"field {n}", "unit": "unknown", "null_count": 3, "samples": [None, 0, "x"]} for n in range(48)]},
        "warnings": ["scope incomplete"], "budget": {"exhausted": ["max_rows"]}, "truncation": {"partial": True}}
    frozen = copy.deepcopy(original)
    result = compact_research_evidence(original)
    def unpack(value):
        if isinstance(value, dict):
            if value.get("encoding") == "columns-and-rows-v1":
                return [dict(zip(value["columns"], row)) for row in value["rows"]]
            return {k: unpack(v) for k,v in value.items()}
        return value
    assert unpack(result) == original == frozen
    assert len(result["preview"]["records"]["rows"]) == 10
    assert size(result) < size(original) * .5
    mixed = {"preview": {"records": [{"a": None}, {"b": 0}]}}
    assert compact_research_evidence(mixed) == mixed  # absent keys do not turn into null


def test_schema_titles_are_removed_but_real_title_field_and_all_constraints_survive():
    schema = DatasetBlueprint.model_json_schema()
    original = copy.deepcopy(schema)
    compact = compact_schema(schema)
    assert schema == original
    assert "title" in compact["$defs"]["BlueprintVisualization"]["properties"]
    assert compact["$defs"]["BlueprintVisualization"]["required"] == original["$defs"]["BlueprintVisualization"]["required"]
    assert size(compact) < size(original)
    assert compact_schema({"title": "label", "const": {"title": "literal"}}) == {"const": {"title": "literal"}}


def test_unknown_timeout_is_not_replayed_as_an_identical_second_request(monkeypatch):
    from app.agent_import import kimi_research_runtime as module
    from app.core.config import settings
    monkeypatch.setattr(settings, "agent_model_authorization_required", False)
    calls = []
    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("synthetic timeout")
    monkeypatch.setattr(module.urlrequest, "urlopen", timeout)
    with pytest.raises(KimiResearchError):
        UrllibJsonTransport(base_url="https://fixture.invalid/v1", api_key="synthetic").request_json(
            "POST", "/chat/completions", body={"model": "fixture"}, timeout=1)
    assert len(calls) == 1


def test_blueprint_repair_receives_exact_local_validation_feedback():
    from test_kimi_research_runtime import _offline_blueprint
    from app.agent_import.kimi_research_runtime import KimiResearchRuntime
    valid = _offline_blueprint()
    invalid = copy.deepcopy(valid)
    invalid["source_assets"][0]["evidence_ids"] = ["not-declared"]
    class Transport:
        def __init__(self):
            self.bodies = []
        def request_json(self, method, path, *, body, timeout):
            self.bodies.append(body)
            data = invalid if len(self.bodies) == 1 else valid
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data)}}]}
    transport = Transport()
    runtime = KimiResearchRuntime(base_url="https://fixture.invalid", api_key="synthetic", model="gpt-fixture", timeout=1, transport=transport)
    result = runtime._parse_blueprint(None, [{"role": "system", "content": "synthetic fixture"},
        {"role": "user", "content": json.dumps({"dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema()})}])
    assert result.source_assets[0].evidence_ids == ["local-tree"]
    assert len(transport.bodies) == 2
    feedback = next(json.loads(m["content"])["validation_errors"] for m in transport.bodies[1]["messages"] if m["role"] == "user" and '"validation_errors"' in m["content"])
    assert "undeclared" in feedback[0]["msg"]
    assert "input" not in feedback[0]


def test_repeated_blueprint_contract_error_is_distinct_from_gateway_failure():
    from app.agent_import.kimi_research_runtime import KimiResearchRuntime, BlueprintValidationError
    class InvalidTransport:
        def request_json(self, *a, **kw):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    runtime = KimiResearchRuntime(base_url="https://fixture.invalid", api_key="synthetic", model="gpt-fixture", timeout=1, transport=InvalidTransport())
    with pytest.raises(BlueprintValidationError) as error:
        runtime._parse_blueprint(None, [{"role": "system", "content": "fixture"}, {"role": "user", "content": json.dumps({"dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema()})}])
    assert error.value.errors
    assert all("input" not in item for item in error.value.errors)
