"""Generic executor preflight for Agent candidate plans."""

from __future__ import annotations

import importlib
import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentBinaryPlanError
from app.agent_import.zp_capabilities import build_zp_capabilities
from app.zp_runtime.package import ensure_binary_layer_importable


def preflight_mapping_plan(
    *,
    source_root: str | Path,
    plan: AgentCandidatePlan,
) -> dict[str, Any]:
    root = Path(source_root).resolve(strict=True)
    if plan.status != "READY" or plan.binary_operation is None or plan.zp_conversion_plan is None:
        raise AgentBinaryPlanError("only a READY executable candidate can pass preflight")
    mapping = plan.zp_conversion_plan.mapping_plan
    if plan.binary_operation != "convert_declared_mapping_to_zp":
        if mapping is not None:
            raise AgentBinaryPlanError("non-mapping operation cannot contain a mapping plan")
        return {
            "schema_version": 1,
            "status": "PASSED",
            "binary_operation": plan.binary_operation,
            "mapping_adapter": None,
        }
    if mapping is None:
        raise AgentBinaryPlanError("declared mapping operation requires mapping_plan")
    adapters = build_zp_capabilities().get("mapping_adapters", {})
    if not isinstance(adapters, dict) or mapping.adapter_id not in adapters:
        raise AgentBinaryPlanError(
            "DatasetBlueprint requires a mapping adapter that Viewer has not implemented yet"
        )
    adapter = adapters[mapping.adapter_id]
    if not isinstance(adapter, dict):
        raise AgentBinaryPlanError("Viewer mapping adapter capability is malformed")
    if plan.analysis_category != adapter.get("analysis_category"):
        raise AgentBinaryPlanError("mapping adapter analysis category does not match the candidate")
    if mapping.source_format != adapter.get("source_format"):
        raise AgentBinaryPlanError("mapping source_format does not match the controlled adapter")
    if mapping.row_policy != "preserve_all_rows":
        raise AgentBinaryPlanError("the controlled MaxQuant adapter must preserve all source rows")
    allowed_transforms = set(adapter.get("allowed_transforms", []))
    if any(item.transform not in allowed_transforms for item in mapping.field_mappings):
        raise AgentBinaryPlanError("mapping plan requests a transform outside the adapter whitelist")

    selected = _selected_source(root, plan)
    ensure_binary_layer_importable()
    service = importlib.import_module("binary_layer.service")
    profile = service.inspect_source(selected)
    if profile.source_type != adapter.get("source_type"):
        raise AgentBinaryPlanError("selected source does not satisfy the controlled mapping adapter")
    bundle = getattr(profile, "composite_bottom_up_bundle", None)
    if bundle is None:
        raise AgentBinaryPlanError("selected source has no inspected composite Bottom-Up bundle")
    actual_by_role = {item.role: item.path.resolve() for item in bundle.source_files}
    declared_by_role = {item.role: item for item in mapping.source_files}
    if len(declared_by_role) != len(mapping.source_files):
        raise AgentBinaryPlanError("mapping source roles must be unique")
    required_roles = adapter.get("required_roles", {})
    optional_roles = adapter.get("optional_roles", {})
    if not isinstance(required_roles, dict) or not isinstance(optional_roles, dict):
        raise AgentBinaryPlanError("Viewer mapping adapter role capability is malformed")
    missing_roles = sorted(set(required_roles) - set(declared_by_role))
    if missing_roles:
        raise AgentBinaryPlanError(
            f"mapping plan omits required source roles: {', '.join(missing_roles)}"
        )
    unknown_roles = sorted(set(declared_by_role) - set(required_roles) - set(optional_roles))
    if unknown_roles:
        raise AgentBinaryPlanError(
            f"mapping plan declares unsupported source roles: {', '.join(unknown_roles)}"
        )
    for role, declared in declared_by_role.items():
        expected = required_roles.get(role) or optional_roles.get(role)
        if not isinstance(expected, dict):
            raise AgentBinaryPlanError(f"mapping role {role} has no capability contract")
        actual_path = actual_by_role.get(role)
        declared_path = _declared_file(root, declared.relative_path)
        if actual_path is None or declared_path != actual_path:
            raise AgentBinaryPlanError(f"mapping role {role} does not match the inspected bundle")
        expected_format = expected.get("source_format")
        if declared.source_format != expected_format:
            raise AgentBinaryPlanError(f"mapping role {role} has an invalid source_format")
        expected_columns = set(expected.get("required_columns", []))
        if not expected_columns.issubset(set(declared.required_columns)):
            raise AgentBinaryPlanError(f"mapping role {role} omits required columns")
        if role in required_roles and declared.required is not True:
            raise AgentBinaryPlanError(f"mapping role {role} must be declared required")
        if role in optional_roles and declared.required is not False:
            raise AgentBinaryPlanError(f"mapping role {role} must remain optional")

    role_by_relative_path = {
        item.relative_path: item.role for item in mapping.source_files
    }
    physical_fields = _physical_fields(bundle, declared_by_role)
    for role, declared in declared_by_role.items():
        unknown_required_columns = sorted(
            set(declared.required_columns) - physical_fields.get(role, set())
        )
        if unknown_required_columns:
            raise AgentBinaryPlanError(
                f"mapping role {role} declares nonexistent required columns: "
                f"{', '.join(unknown_required_columns)}"
            )
    actual_mapping_contract: set[
        tuple[str, str, str, str, str, str | None, str]
    ] = set()
    for field_mapping in mapping.field_mappings:
        role = role_by_relative_path[field_mapping.source_file]
        if field_mapping.source_field not in physical_fields.get(role, set()):
            raise AgentBinaryPlanError(
                f"mapping source field does not exist for role {role}: {field_mapping.source_field}"
            )
        actual_mapping_contract.add(
            (
                role,
                field_mapping.source_field,
                field_mapping.target_entity,
                field_mapping.target_field,
                field_mapping.value_kind,
                field_mapping.unit,
                field_mapping.transform,
            )
        )
    if len(actual_mapping_contract) != len(mapping.field_mappings):
        raise AgentBinaryPlanError("mapping plan contains duplicate field mappings")
    required_mapping_contract = {
        tuple(item)
        for item in adapter.get("required_field_mappings", [])
        if isinstance(item, list) and len(item) == 7
    }
    if actual_mapping_contract != required_mapping_contract:
        raise AgentBinaryPlanError("mapping plan does not exactly match the adapter's canonical field mappings")
    for item in mapping.field_mappings:
        role = role_by_relative_path[item.source_file]
        identity = (
            role,
            item.source_field,
            item.target_entity,
            item.target_field,
            item.value_kind,
            item.unit,
            item.transform,
        )
        if identity in required_mapping_contract and item.required is not True:
            raise AgentBinaryPlanError("canonical field mappings must be declared required")

    actual_joins = {
        (
            role_by_relative_path[item.left_file],
            item.left_field,
            role_by_relative_path[item.right_file],
            item.right_field,
            item.cardinality,
            item.transform,
        )
        for item in mapping.join_rules
    }
    required_joins = {
        tuple(item)
        for item in adapter.get("required_join_rules", [])
        if isinstance(item, list) and len(item) == 6
    }
    if len(actual_joins) != len(mapping.join_rules):
        raise AgentBinaryPlanError("mapping plan contains duplicate join rules")
    if actual_joins != required_joins:
        raise AgentBinaryPlanError("mapping join rules do not exactly match the controlled adapter")

    expected_count_keys = set(adapter.get("expected_count_keys", []))
    if set(mapping.expected_counts) != expected_count_keys:
        raise AgentBinaryPlanError("mapping expected_counts do not match the adapter contract")
    mzml_counts = _mzml_core_counts(bundle.spectrum_source)
    actual_counts = {
        "spectra": mzml_counts[0],
        "precursors": mzml_counts[1],
        "evidence_rows": bundle.evidence_row_count,
        "protein_groups": bundle.protein_group_row_count,
    }
    if mapping.expected_counts != actual_counts:
        raise AgentBinaryPlanError("mapping expected_counts do not match the inspected source")

    for relative_path, fields in mapping.unmapped_fields.items():
        role = role_by_relative_path[relative_path]
        missing = sorted(set(fields) - physical_fields.get(role, set()))
        if missing:
            raise AgentBinaryPlanError(
                f"unmapped_fields contains nonexistent fields for role {role}: {', '.join(missing)}"
            )
    for evidence in mapping.evidence:
        if evidence.source_field is None:
            continue
        role = role_by_relative_path[evidence.source_file]
        if evidence.source_field not in physical_fields.get(role, set()):
            raise AgentBinaryPlanError(
                f"mapping evidence references a nonexistent field for role {role}"
            )

    return {
        "schema_version": 1,
        "status": "PASSED",
        "binary_operation": plan.binary_operation,
        "mapping_adapter": mapping.adapter_id,
        "source_type": profile.source_type,
        "detected_roles": list(profile.detected_roles),
    }


def _selected_source(root: Path, plan: AgentCandidatePlan) -> Path:
    assert plan.zp_conversion_plan is not None
    try:
        selected = root.joinpath(*Path(plan.zp_conversion_plan.relative_source).parts).resolve(
            strict=True
        )
    except OSError as exc:
        raise AgentBinaryPlanError("relative_source does not exist or cannot be accessed") from exc
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise AgentBinaryPlanError("relative_source escapes the Case source root") from exc
    return selected


def _declared_file(root: Path, relative_path: str) -> Path:
    try:
        selected = root.joinpath(*Path(relative_path).parts).resolve(strict=True)
    except OSError as exc:
        raise AgentBinaryPlanError("mapping source file does not exist or cannot be accessed") from exc
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise AgentBinaryPlanError("mapping source file escapes the Case source root") from exc
    if not selected.is_file():
        raise AgentBinaryPlanError("mapping source file is not a regular file")
    return selected


def _physical_fields(bundle: Any, declared_by_role: dict[str, Any]) -> dict[str, set[str]]:
    result = {
        "evidence": set(bundle.evidence_columns),
        "protein_groups": set(bundle.protein_group_columns),
        "spectrum_source": {
            "scan_number",
            "ms_level",
            "rt_seconds",
            "native_id",
            "mz_array",
            "intensity_array",
        },
        "vendor_raw": set(),
        "fasta": {"accession", "header", "sequence"},
    }
    if bundle.summary is not None:
        result["summary"] = set(_tabular_header(bundle.summary))
    if bundle.mqpar is not None:
        result["parameters"] = _xml_tag_names(bundle.mqpar)
    if bundle.metadata_json is not None:
        result["vendor_metadata"] = _json_field_names(bundle.metadata_json)
    for role in declared_by_role:
        result.setdefault(role, set())
    return result


def _tabular_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream, delimiter="\t"), None)
    except OSError as exc:
        raise AgentBinaryPlanError("mapping table header cannot be read") from exc
    if not header:
        raise AgentBinaryPlanError("mapping table header is empty")
    return tuple(header)


def _xml_tag_names(path: Path) -> set[str]:
    result: set[str] = set()
    try:
        for _event, element in ET.iterparse(path, events=("end",)):
            result.add(element.tag.rsplit("}", 1)[-1])
            element.clear()
    except (OSError, ET.ParseError) as exc:
        raise AgentBinaryPlanError("mapping XML fields cannot be inspected") from exc
    return result


def _json_field_names(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentBinaryPlanError("mapping JSON fields cannot be inspected") from exc
    result: set[str] = set()
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            result.update(str(key) for key in value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return result


def _mzml_core_counts(path: Path) -> tuple[int, int]:
    spectra = 0
    ms2 = 0
    try:
        for _event, element in ET.iterparse(path, events=("end",)):
            if element.tag.rsplit("}", 1)[-1] != "spectrum":
                continue
            spectra += 1
            level = next(
                (
                    child.attrib.get("value")
                    for child in element.iter()
                    if child.tag.rsplit("}", 1)[-1] == "cvParam"
                    and child.attrib.get("accession") == "MS:1000511"
                ),
                None,
            )
            if level == "2":
                ms2 += 1
            element.clear()
    except (OSError, ET.ParseError) as exc:
        raise AgentBinaryPlanError("mapping mzML counts cannot be inspected") from exc
    if spectra <= 0 or ms2 <= 0:
        raise AgentBinaryPlanError("mapping mzML contains no usable MS1/MS2 core")
    return spectra, ms2
