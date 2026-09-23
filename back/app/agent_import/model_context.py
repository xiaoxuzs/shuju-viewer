"""Bound model-visible context without mutating retained evidence or executable contracts."""
from __future__ import annotations

import itertools
import json

from app.agent_import.errors import AgentImportError
from app.source_inspection.preview import bounded_value

MAX_REQUEST_BYTES = 196_608
MAX_TOOL_BYTES = 32_768
MAX_TOOL_SESSION_BYTES = 131_072
MAX_OBSERVATION_BYTES = 65_536


def size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def manifest_view(manifest):
    files = manifest.get("files", [])
    return {"file_count": manifest.get("file_count"), "truncated": manifest.get("truncated"),
            "files": [{k: item[k] for k in ("relative_path", "size_bytes", "suffix") if k in item} for item in files[:40]],
            "additional_files": max(0, len(files) - 40), "pagination_tool": "list_source_inventory"}


def evidence_view(value, depth=0):
    if depth > 12:
        return {"omitted": "depth_limit"}
    if isinstance(value, dict):
        return {k: evidence_view(v, depth + 1) for k, v in itertools.islice(value.items(), 64)
                if k not in {"raw_content", "binary", "base64", "peak_arrays", "samples_text"}}
    if isinstance(value, list):
        # Column schema and structural vocabulary can have >10 entries, raw record lists cannot.
        cap = 64 if all(isinstance(v, dict) and ("name" in v or "field" in v) for v in value) else 10
        return [evidence_view(v, depth + 1) for v in value[:cap]]
    return bounded_value(value)


def observation_views(observations, *, include_previews=True, executed_source_paths=None):
    result = []
    selected = [item for item in observations if isinstance(item, dict)][:64]
    metadata = []
    for item in selected:
        payload = item.get("payload", {})
        facts = payload.get("facts", {}) if isinstance(payload, dict) else {}
        fields = {}
        for field in [*(facts.get("columns") or []), *(facts.get("fields") or [])]:
            if isinstance(field, dict) and isinstance(field.get("name"), str):
                fields.setdefault(field["name"], {}).update({k: field[k] for k in ("name", "unit", "inferred_type") if k in field})
            elif isinstance(field, str):
                fields.setdefault(field, {"name": field})
        metadata.append({"relative_path": payload.get("relative_path"), "physical_fields": list(fields.values())[:256],
            "reported_field_count": facts.get("column_count", len(fields)), "field_names_complete": len(fields) <= 256 and len(fields) == facts.get("column_count", len(fields))})
    bases = [{**{k: item.get(k) for k in ("call_id", "tool_name", "status", "result_sha256")},
              "source_schema": schema,
              "payload_omitted": "model observation budget; retained by artifact reference"}
             for item, schema in zip(selected, metadata)]
    used = size(bases)
    if used > MAX_OBSERVATION_BYTES:
        raise AgentImportError("MODEL_CONTEXT_BUDGET_EXCEEDED", "Source schemas exceed the observation budget; narrow field scope before model egress.", status_code=409)
    for item, base in zip(selected, bases):
        raw = item.get("payload", {})
        if not include_previews:
            raw = _without_previews(raw)
            if item.get("tool_name") == "inspect_viewer_capabilities":
                raw = {"capability_reference": "Use the separately supplied current zp_capabilities; the original research capability observation remains retained by result_sha256."}
            # Transport timings/hashes are retained in the original observation;
            # its reference/hash and the source manifest already identify them.
            raw = {key: value for key, value in raw.items() if key not in {
                "budget", "hashes", "inspector_id", "inspector_version", "source_mtime_ns", "source_size_bytes"}}
            if executed_source_paths is not None and raw.get("relative_path") not in executed_source_paths and isinstance(raw.get("facts"), dict):
                raw = {**raw, "facts": {key: value for key, value in raw["facts"].items() if key != "columns"},
                    "column_statistics_omitted": "Not a Blueprint binary-content source; full physical schema remains in source_schema and original statistics remain by observation reference."}
        payload = compact_research_evidence(evidence_view(raw))
        view = {**{k: v for k, v in base.items() if k != "payload_omitted"}, "payload": payload, "model_view_only": True,
                "view_truncated": payload != item.get("payload", {})}
        extra = size(view) - size(base)
        if used + extra > MAX_OBSERVATION_BYTES:
            view = base
        else:
            used += extra
        result.append(view)
        if len(result) >= 64:
            break
    return result


def _without_previews(value, path=()):
    """Downstream roles retain inspected facts/schema, not repeated raw previews."""
    if isinstance(value, dict):
        return {key: ({"omitted": "Research preview retained by observation hash; use physical schema and inspected facts"}
                      if key == "preview" else _without_previews(item, (*path, key))) for key, item in value.items()
                if not (key == "samples" and path[-3:] == ("facts", "columns", "[]"))}
    if isinstance(value, list):
        return [_without_previews(item, (*path, "[]")) for item in value]
    return value


def enforce_request(body):
    byte_count = size(body)
    if byte_count > MAX_REQUEST_BYTES:
        raise AgentImportError("MODEL_CONTEXT_BUDGET_EXCEEDED", "Final model request exceeds its byte budget; narrow research using artifact references. No partial contract was executed.", status_code=409)
    return body


def blueprint_view(blueprint):
    """Preserve structured proposals; raw free-form details get bounded, visibly marked views."""
    if not isinstance(blueprint, dict):
        return blueprint
    def visit(value, key=""):
        if key in {"details", "source_fields"}:
            return bounded_value(value)
        if isinstance(value, dict):
            return {k: visit(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v) for v in value]
        if isinstance(value, str) and len(value) > 1024:
            return value[:1024] + " [model-view truncated; consult retained evidence]"
        return value
    view = visit(blueprint)
    return {**view, "model_view_truncated": view != blueprint}


def message_views(messages):
    # Arbitrary prose can contain a pasted raw file; do not forward a large historical dump.
    selected = list(messages[-20:])
    if any(len(m.encode("utf-8")) > 8192 for m in selected) or size(selected) > 16_384:
        raise AgentImportError("MODEL_CONTEXT_BUDGET_EXCEEDED", "User-message context is too large; retained messages need a scoped requirement summary before model egress.", status_code=409)
    return selected


def compact_schema(schema):
    """Remove generated display titles, never constraints, refs or descriptions."""
    if isinstance(schema, dict):
        result = {}
        for key, value in schema.items():
            if key == "title":
                continue
            if key in {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"} and isinstance(value, dict):
                result[key] = {name: compact_schema(child) for name, child in value.items()}
            elif key in {"const", "enum", "default", "examples"}:
                result[key] = value
            else:
                result[key] = compact_schema(value)
        return result
    if isinstance(schema, list):
        return [compact_schema(v) for v in schema]
    return schema


def compact_research_evidence(value, path=()):
    """Lossless table encoding of already-bounded evidence, not scientific summarization.

    Repeated column names dominate wide-table previews and column statistics.
    Only these two known inspection containers are encoded; all records, nulls,
    zeros, units, warnings, partial-scan flags and source references survive.
    Original observations/hashes remain untouched for downstream preflight.
    """
    if isinstance(value, dict):
        return {k: compact_research_evidence(v, (*path, k)) for k, v in value.items()}
    if isinstance(value, list):
        items = [compact_research_evidence(v, (*path, "[]")) for v in value]
        if path[-2:] not in {("preview", "records"), ("facts", "columns")} or len(items) < 2:
            return items
        if not all(isinstance(v, dict) for v in items):
            return items
        columns = list(items[0])
        if not columns or not all(set(v) == set(columns) for v in items):
            return items  # missing key is not interchangeable with null
        table = {"encoding": "columns-and-rows-v1", "columns": columns,
                 "rows": [[row[key] for key in columns] for row in items]}
        return table if size(table) < size(items) else items
    return value
