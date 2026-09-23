"""Apply only an explicit model-proposed bounded JSON patch; validate the whole Blueprint afterwards."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .source_code import canonical_bytes, digest_bytes


class BlueprintEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"allOf": [{
        "if": {"properties": {"op": {"enum": ["add", "replace"]}}, "required": ["op"]},
        "then": {"required": ["value"]},
    }]})
    op: Literal["add", "replace", "remove"]
    path: str = Field(min_length=2, max_length=512)
    value: JsonValue = None

    @model_validator(mode="after")
    def explicit_value(self):
        if self.op != "remove" and "value" not in self.model_fields_set:
            raise ValueError("Add/replace requires an explicit value, including explicit null")
        return self


class BlueprintPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    edits: list[BlueprintEdit] = Field(min_length=1, max_length=24)


# Shared pure JSON operation; role prompts, validators and execution rights stay separate.
ModelJsonPatch = BlueprintPatch


def apply_blueprint_patch(base: dict, proposal: dict) -> dict:
    patch = BlueprintPatch.model_validate(proposal)
    if patch.base_sha256 != digest_bytes(canonical_bytes(base)):
        raise ValueError("Blueprint repair baseline mismatch")
    result = deepcopy(base)
    for edit in patch.edits:
        if not edit.path.startswith("/") or edit.path == "/":
            raise ValueError("Repair must name a JSON field, not replace the whole document")
        parts = edit.path[1:].split("/")
        if len(parts) > 12 or any("~" in p.replace("~0", "").replace("~1", "") for p in parts):
            raise ValueError("Invalid or excessive JSON pointer")
        parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]
        target = result
        for part in parts[:-1]:
            if isinstance(target, dict):
                if part not in target:
                    raise ValueError("Repair parent field is absent")
                target = target[part]
            elif isinstance(target, list) and part.isdigit() and str(int(part)) == part:
                if int(part) >= len(target):
                    raise ValueError("Repair parent index is invalid")
                target = target[int(part)]
            else:
                raise ValueError("Repair path does not name a container")
        key = parts[-1]
        if isinstance(target, dict):
            if edit.op in {"replace", "remove"} and key not in target:
                raise ValueError("Repair field is absent")
            if edit.op == "remove":
                del target[key]
            else:
                target[key] = edit.value
        elif isinstance(target, list):
            index = len(target) if key == "-" and edit.op == "add" else int(key) if key.isdigit() and str(int(key)) == key else -1
            if index < 0 or index > len(target) or edit.op != "add" and index == len(target):
                raise ValueError("Repair array index is invalid")
            if edit.op == "add": target.insert(index, edit.value)
            elif edit.op == "replace": target[index] = edit.value
            else: target.pop(index)
        else:
            raise ValueError("Repair path does not name a container")
    return result
