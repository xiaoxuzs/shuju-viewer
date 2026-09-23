from copy import deepcopy
import json

import pytest

from app.agent_import.blueprint_repair import apply_blueprint_patch
from app.agent_import.kimi_research_runtime import KimiResearchRuntime, BlueprintValidationError
from app.agent_import.research_contracts import DatasetBlueprint
from app.agent_import.source_code import canonical_bytes, digest_bytes


def test_actual_model_patch_is_applied_to_exact_baseline_then_whole_contract_checked():
    from test_kimi_research_runtime import _offline_blueprint
    valid = _offline_blueprint()
    invalid = deepcopy(valid)
    invalid["source_assets"][0]["evidence_ids"] = ["not-declared"]
    calls, diagnostics = [], []
    class Transport:
        def request_json(self, method, path, *, body, timeout):
            calls.append(body)
            answer = invalid if len(calls) == 1 else {"base_sha256": digest_bytes(canonical_bytes(invalid)),
                "edits": [{"op": "replace", "path": "/source_assets/0/evidence_ids", "value": ["local-tree"]}]}
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}
    runtime = KimiResearchRuntime(base_url="http://fixture.invalid", api_key="synthetic", model="gpt-fixture", timeout=1,
        max_output_tokens=4096, transport=Transport(), diagnostic_sink=diagnostics.append)
    result = runtime._parse_blueprint(None, [{"role": "system", "content": "fixture"}, {"role": "user", "content": json.dumps({"dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema()})}])
    assert result.model_dump(mode="json") == DatasetBlueprint.model_validate(valid).model_dump(mode="json")
    assert calls[1]["max_completion_tokens"] == 1536
    assert diagnostics[0]["kind"] == "blueprint_validation_rejected"
    assert diagnostics[1]["patch"]["edits"][0]["path"] == "/source_assets/0/evidence_ids"
    assert invalid["source_assets"][0]["evidence_ids"] == ["not-declared"]


@pytest.mark.parametrize("path", ["/absent/child", "/items/999/value", "/items/-1", "/items/01", "/", "/items/~8"])
def test_bad_patch_paths_do_not_mutate_or_escape_the_json_object(path):
    base = {"items": [{"value": 1}]}
    original = deepcopy(base)
    with pytest.raises(ValueError):
        apply_blueprint_patch(base, {"base_sha256": digest_bytes(canonical_bytes(base)), "edits": [{"op": "replace", "path": path, "value": 2}]})
    assert base == original


def test_patch_cannot_use_a_different_baseline_or_relax_whole_contract():
    base = {"items": []}
    with pytest.raises(ValueError, match="baseline"):
        apply_blueprint_patch(base, {"base_sha256": "0" * 64, "edits": [{"op": "add", "path": "/items/-", "value": 1}]})
    patched = apply_blueprint_patch(base, {"base_sha256": digest_bytes(canonical_bytes(base)), "edits": [{"op": "add", "path": "/items/-", "value": 1}]})
    with pytest.raises(ValueError):
        DatasetBlueprint.model_validate(patched)
    with pytest.raises(ValueError, match="explicit value"):
        apply_blueprint_patch(base, {"base_sha256": digest_bytes(canonical_bytes(base)), "edits": [{"op": "replace", "path": "/items"}]})


def test_rejected_blueprint_is_retained_even_when_repair_transport_times_out():
    records = []
    class Transport:
        calls = 0
        def request_json(self, *a, **k):
            self.calls += 1
            if self.calls == 2: raise TimeoutError("fixture")
            return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    runtime = KimiResearchRuntime(base_url="http://fixture.invalid", api_key="synthetic", model="gpt-fixture", timeout=1, transport=Transport(), diagnostic_sink=records.append)
    with pytest.raises(TimeoutError):
        runtime._parse_blueprint(None, [{"role": "system", "content": "fixture"}, {"role": "user", "content": json.dumps({"dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema()})}])
    assert len(records) == 1 and records[0]["errors"]
