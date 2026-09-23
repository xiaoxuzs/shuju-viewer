"""Deterministic physical and semantic checks for declarative import plans."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import pyarrow.parquet as pq
from app.source_inspection import InventoryService
from app.dataset_capabilities import VIEWER_VIEW_CATALOG

from .contracts import DeclarativeImportPlan, DeclarativeSource, FieldMapping


class DeclarativePlanError(ValueError):
    def __init__(self, message: str, *, code: str = "DECLARATIVE_PLAN_INVALID") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class DeclarativePreflightReport:
    status: str
    source_fields: dict[str, tuple[str, ...]]
    mapped_field_count: int
    explicitly_unmapped_field_count: int
    requested_view_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status,
            "source_fields": {key: list(value) for key, value in self.source_fields.items()},
            "mapped_field_count": self.mapped_field_count,
            "explicitly_unmapped_field_count": self.explicitly_unmapped_field_count,
            "requested_view_ids": list(self.requested_view_ids),
        }


_TARGET_FIELDS: dict[str, frozenset[str]] = {
    "run": frozenset({"name"}),
    "spectrum": frozenset({"scan_number", "native_id"}),
    "identification": frozenset(
        {
            "source_id",
            "is_decoy",
            "modified_sequence",
            "charge",
            "precursor_mz",
            "neutral_mass",
            "rt_seconds",
            "scan_number",
            "score",
            "q_value",
            "pep",
            "protein_accessions",
            "protein_group_ids",
        }
    ),
    "peptide": frozenset({"sequence"}),
    "protein": frozenset({"accession", "name", "gene", "description", "is_decoy"}),
    "protein_group": frozenset({"source_id", "member_accessions", "leading_accession", "q_value", "pep"}),
    "modification": frozenset({"name", "accession", "mass_shift", "position", "residue", "localization_probability"}),
    "quantification": frozenset({"value", "channel", "sample", "normalization_kind"}),
}

_LIST_TARGETS = frozenset(
    {
        ("identification", "protein_accessions"),
        ("identification", "protein_group_ids"),
        ("protein_group", "member_accessions"),
    }
)
_INTEGER_TARGETS = frozenset(
    {
        ("identification", "charge"),
        ("identification", "scan_number"),
        ("spectrum", "scan_number"),
        ("modification", "position"),
    }
)
_FLOAT_TARGETS = frozenset(
    {
        ("identification", "precursor_mz"),
        ("identification", "neutral_mass"),
        ("identification", "rt_seconds"),
        ("identification", "score"),
        ("identification", "q_value"),
        ("identification", "pep"),
        ("protein_group", "q_value"),
        ("protein_group", "pep"),
        ("modification", "mass_shift"),
        ("modification", "localization_probability"),
        ("quantification", "value"),
    }
)
_BOOLEAN_TARGETS = frozenset({("protein", "is_decoy"), ("identification", "is_decoy")})


def build_declarative_ingest_capabilities() -> dict[str, Any]:
    """Return the exact primitive vocabulary accepted by this executor."""

    return {
        "schema_version": 1,
        "protocol": "viewer_declarative_bottom_up_v1",
        "analysis_modes": ["BOTTOM_UP"],
        "readers": ["delimited", "jsonl", "parquet", "mzml", "fasta"],
        "semantic_write_version": 2,
        "semantic_read_versions": [1, 2],
        "identification_identity": {"mapped": "source ID scoped by source and run", "source_row": "Set on a tabular source when no unique physical ID exists. Omit identification.source_id mapping; preserve every input record with 1-based parsed record number and keep original ID in source_fields."},
        "reader_modes": {
            "delimited": "entity_rows",
            "jsonl": "entity_rows",
            "parquet": "entity_rows",
            "mzml": "spectrum_companion",
            "fasta": "sequence_companion",
        },
        "field_mapping_readers": ["delimited", "jsonl", "parquet"],
        "companion_ingestion": "mzML and FASTA are automatically read by the trusted companion readers. Do NOT add field_mappings for their virtual scan_number/native_id/accession/header/sequence fields. mzML supplies all spectra/arrays/precursors/chromatograms; FASTA attaches sequences through fasta_accession_rule. Map scientific entities from the tabular sources only.",
        "transforms": [
            "identity",
            "trim",
            "minute_to_second",
            "semicolon_split",
            "singleton_list",
            "first_semicolon_value",
            "plus_marker_to_bool",
        ],
        "target_fields": {
            entity: sorted(fields, key=lambda item: item.encode("utf-8"))
            for entity, fields in _TARGET_FIELDS.items()
        },
        "target_contracts": {
            f"{entity}.{field}": _target_contract(entity, field)
            for entity, fields in _TARGET_FIELDS.items()
            for field in sorted(fields, key=lambda item: item.encode("utf-8"))
        },
        "registered_views": {
            view_id: {
                "title": spec.title,
                "route": spec.route,
                "analysis_modes": list(spec.analysis_modes),
                "requirements": [
                    {"entity": item.entity, "required": item.required}
                    for item in spec.requirements
                ],
            }
            for view_id, spec in VIEWER_VIEW_CATALOG.items()
        },
        "relationship_kinds": ["identification_to_spectrum"],
        "companion_fields": {
            "mzml": ["scan_number", "native_id", "ms_level", "rt_seconds", "mz_array", "intensity_array"],
            "fasta": ["accession", "header", "sequence"],
        },
        "spectrum_join_contract": {
            "left": "Physical field mapped to identification.scan_number",
            "right_reader": "mzml", "right_field": "scan_number", "transform": "identity",
            "cardinality": ["many_to_one", "one_to_one"],
            "run_scope": "The trusted executor independently requires exactly one semantic run and one mzML core run with the declared source path. Do not add a separate run/run_name join: those are not mzML fields.",
        },
        "rules": [
            "Every physical tabular field must be mapped, used by a join, or listed in unmapped_fields.",
            "Retention-time mappings must prove their source unit.",
            "Only exact declared joins may create scientific relationships.",
            "Optional missing modules are reported; missing values are never fabricated.",
            "The first version accepts at most one mzML source but permits table-only datasets.",
            "Declaring any mzML source requires acquisition_mode (dda/dia) and nonempty acquisition_mode_evidence_refs.",
            "Acquisition mode cannot be guessed from the software name or the presence of MS2 scans; without trusted evidence return NEEDS_USER and ask for confirmation.",
            "Quantification and modification mappings attach only to an identification row in schema v1.",
            "Protein sequences are accepted only from a declared FASTA companion in schema v1.",
        ],
    }


def _target_contract(entity: str, field: str) -> dict[str, Any]:
    target = (entity, field)
    if target in _LIST_TARGETS:
        return {
            "output_shape": "list",
            "allowed_value_kinds": ["string"],
            "allowed_transforms": ["semicolon_split", "singleton_list"],
        }
    if target in _INTEGER_TARGETS:
        return {
            "output_shape": "scalar",
            "allowed_value_kinds": ["integer"],
            "allowed_transforms": ["identity"],
        }
    if target in _FLOAT_TARGETS:
        transforms = ["identity", "minute_to_second"] if target == ("identification", "rt_seconds") else ["identity"]
        return {
            "output_shape": "scalar",
            "allowed_value_kinds": ["float"],
            "allowed_transforms": transforms,
        }
    if target in _BOOLEAN_TARGETS:
        return {
            "output_shape": "scalar",
            "allowed_value_kinds": ["boolean"],
            "allowed_transforms": ["identity", "plus_marker_to_bool"],
        }
    transforms = ["identity", "trim", "first_semicolon_value"]
    if target in {("protein", "accession"), ("modification", "name")}:
        transforms.append("semicolon_split")
    return {
        "output_shape": "scalar_or_expanded_records" if "semicolon_split" in transforms else "scalar",
        "allowed_value_kinds": ["string", "integer"],
        "allowed_transforms": transforms,
    }


def preflight_declarative_plan(
    *,
    source_root: str | Path,
    plan: DeclarativeImportPlan,
    trusted_observations: Mapping[str, dict[str, Any]] | None = None,
) -> DeclarativePreflightReport:
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise DeclarativePlanError("source_root must be a directory")
    declared_sources = {source.source_id: source for source in plan.sources}
    for mapping in plan.field_mappings:
        source = declared_sources[mapping.source_id]
        if source.reader not in {"delimited", "jsonl", "parquet"}:
            raise DeclarativePlanError(f"mapping {mapping.mapping_id}: {source.reader} companion is ingested automatically; field_mappings accept tabular sources only. Keep the companion source, remove its virtual-field mappings.")
    if trusted_observations is not None:
        _validate_evidence_bindings(plan, trusted_observations)
    incompatible_views = [
        item.view_id
        for item in plan.requested_views
        if (spec := VIEWER_VIEW_CATALOG.get(item.view_id)) is not None
        and plan.analysis_mode not in spec.analysis_modes
    ]
    if incompatible_views:
        raise DeclarativePlanError(
            "requested views are incompatible with the plan analysis mode: "
            + ", ".join(sorted(incompatible_views))
        )
    source_fields: dict[str, tuple[str, ...]] = {}
    sources = {item.source_id: item for item in plan.sources}
    for source in plan.sources:
        path = _resolve_source(root, source)
        fields = _physical_fields(path, source)
        source_fields[source.source_id] = fields
        missing = sorted(set(source.required_fields) - set(fields))
        if missing:
            raise DeclarativePlanError(
                f"source {source.source_id} is missing required fields: {', '.join(missing)}"
            )

    seen_targets: set[tuple[str, str, str, str | None]] = set()
    for mapping in plan.field_mappings:
        source = sources[mapping.source_id]
        if source.reader not in {"delimited", "jsonl", "parquet"}:
            raise DeclarativePlanError(
                f"reader {source.reader} cannot emit entity field mappings in declarative schema v1"
            )
        fields = set(source_fields[mapping.source_id])
        if mapping.source_field not in fields:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} references missing field {mapping.source_field}"
            )
        allowed = _TARGET_FIELDS[mapping.target_entity]
        if mapping.target_field not in allowed:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} targets unsupported canonical field "
                f"{mapping.target_entity}.{mapping.target_field}"
            )
        identity = (
            mapping.source_id,
            mapping.target_entity,
            mapping.target_field,
            mapping.measurement_name
            if mapping.target_entity == "quantification" and mapping.target_field == "value"
            else None,
        )
        if identity in seen_targets:
            raise DeclarativePlanError(
                f"multiple mappings target {mapping.target_entity}.{mapping.target_field} in source {mapping.source_id}"
            )
        seen_targets.add(identity)
        _validate_target_shape(mapping)
        _validate_unit_and_transform(mapping)
        _validate_observed_delimiter(
            _resolve_source(root, source),
            source,
            mapping,
        )

    for join in plan.join_rules:
        if join.left_field not in source_fields[join.left_source_id]:
            raise DeclarativePlanError(f"join {join.join_id} references missing left field")
        if join.right_field not in source_fields[join.right_source_id]:
            raise DeclarativePlanError(f"join {join.join_id} references missing right field")
        left_mapping = next(
            (
                item
                for item in plan.field_mappings
                if item.source_id == join.left_source_id
                and item.source_field == join.left_field
                and item.target_entity == "identification"
                and item.target_field == "scan_number"
            ),
            None,
        )
        right_source = sources[join.right_source_id]
        if (
            left_mapping is None
            or right_source.reader != "mzml"
            or join.right_field != "scan_number"
            or join.transform != "identity"
            or join.cardinality not in {"many_to_one", "one_to_one"}
        ):
            raise DeclarativePlanError(
                f"join {join.join_id} is outside the v1 exact scan-to-mzML contract",
                code="SCIENTIFIC_SEMANTIC_UNKNOWN",
            )

    measurements: dict[str, list[FieldMapping]] = {}
    for mapping in plan.field_mappings:
        if mapping.target_entity == "quantification" and mapping.target_field == "value":
            measurements.setdefault(mapping.source_id, []).append(mapping)
    for source_id, items in measurements.items():
        _require_identification_row_mappings(plan, source_id, feature="quantification")
        if len(items) > 1 and any(item.measurement_name is None for item in items):
            raise DeclarativePlanError(
                f"source {source_id} has multiple measurements but a measurement_name is missing"
            )
    for source_id in {
        item.source_id for item in plan.field_mappings if item.target_entity == "modification"
    }:
        _require_identification_row_mappings(plan, source_id, feature="modification")
    for source_id in {
        item.source_id for item in plan.field_mappings if item.target_entity == "spectrum"
    }:
        _require_identification_row_mappings(plan, source_id, feature="spectrum reference")

    tabular_source_ids = {
        item.source_id for item in plan.sources if item.reader in {"delimited", "jsonl", "parquet"}
    }
    for source_id in tabular_source_ids:
        mapped = {
            item.source_field for item in plan.field_mappings if item.source_id == source_id
        }
        joined = {
            field
            for item in plan.join_rules
            for candidate_source, field in (
                (item.left_source_id, item.left_field),
                (item.right_source_id, item.right_field),
            )
            if candidate_source == source_id
        }
        accounted = mapped | joined | set(plan.unmapped_fields.get(source_id, []))
        unaccounted = sorted(set(source_fields[source_id]) - accounted)
        nonexistent = sorted(set(plan.unmapped_fields.get(source_id, [])) - set(source_fields[source_id]))
        if nonexistent:
            raise DeclarativePlanError(
                f"unmapped_fields[{source_id}] references nonexistent fields: {', '.join(nonexistent)}"
            )
        if unaccounted:
            raise DeclarativePlanError(
                f"source {source_id} has fields that are neither mapped nor explicitly unmapped: "
                f"{', '.join(unaccounted)}"
            )

    physical_assets = _inventory_paths(root)
    declared_assets = {item.relative_path for item in plan.sources if _resolve_source(root, item).is_file()}
    disposed_assets = {item.relative_path for item in plan.asset_dispositions}
    nonexistent_dispositions = sorted(disposed_assets - physical_assets)
    if nonexistent_dispositions:
        raise DeclarativePlanError(
            "asset_dispositions references nonexistent files: " + ", ".join(nonexistent_dispositions)
        )
    unaccounted_assets = sorted(physical_assets - declared_assets - disposed_assets)
    if unaccounted_assets:
        preview = ", ".join(unaccounted_assets[:20])
        suffix = f"; and {len(unaccounted_assets) - 20} more" if len(unaccounted_assets) > 20 else ""
        raise DeclarativePlanError(
            f"source files have no input or explicit disposition: {preview}{suffix}"
        )

    _require_bottom_up_identity(plan, sources)
    return DeclarativePreflightReport(
        status="PASSED",
        source_fields=source_fields,
        mapped_field_count=len(plan.field_mappings),
        explicitly_unmapped_field_count=sum(len(value) for value in plan.unmapped_fields.values()),
        requested_view_ids=tuple(item.view_id for item in plan.requested_views),
    )


def _resolve_source(root: Path, source: DeclarativeSource) -> Path:
    try:
        path = root.joinpath(*Path(source.relative_path).parts).resolve(strict=True)
    except OSError as exc:
        if source.required:
            raise DeclarativePlanError(
                f"required source does not exist: {source.source_id}",
                code="MISSING_REQUIRED_COMPANION_FILE",
            ) from exc
        return root / source.relative_path
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DeclarativePlanError(f"source escapes Case root: {source.source_id}") from exc
    if path.is_symlink() or not path.is_file():
        raise DeclarativePlanError(f"source must be a regular non-symlink file: {source.source_id}")
    return path


def _physical_fields(path: Path, source: DeclarativeSource) -> tuple[str, ...]:
    if not path.exists() and not source.required:
        return ()
    if source.reader == "delimited":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                header = next(csv.reader(stream, delimiter=source.delimiter or "\t"), None)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise DeclarativePlanError(f"cannot read delimited header: {source.source_id}") from exc
        if not header or any(not item for item in header) or len(header) != len(set(header)):
            raise DeclarativePlanError(f"source has an invalid or duplicate header: {source.source_id}")
        return tuple(header)
    if source.reader == "jsonl":
        return _jsonl_fields(path, source.source_id)
    if source.reader == "parquet":
        try:
            return tuple(pq.ParquetFile(path).schema_arrow.names)
        except (OSError, ValueError) as exc:
            raise DeclarativePlanError(f"cannot read parquet schema: {source.source_id}") from exc
    if source.reader == "fasta":
        return ("accession", "header", "sequence")
    if source.reader == "mzml":
        return ("scan_number", "native_id", "ms_level", "rt_seconds", "mz_array", "intensity_array")
    raise DeclarativePlanError(f"unsupported reader: {source.reader}")


def _jsonl_fields(path: Path, source_id: str) -> tuple[str, ...]:
    fields: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DeclarativePlanError(f"JSONL row {line_no} is not an object: {source_id}")
                fields.update(str(key) for key in value)
                from app.agent_import.execution_control import checkpoint
                if line_no % 4096 == 0:
                    checkpoint()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeclarativePlanError(f"cannot inspect JSONL schema: {source_id}") from exc
    if not fields:
        raise DeclarativePlanError(f"JSONL source is empty: {source_id}")
    return tuple(sorted(fields, key=lambda item: item.encode("utf-8")))


def _validate_unit_and_transform(mapping: FieldMapping) -> None:
    if mapping.target_field == "rt_seconds":
        if mapping.transform == "minute_to_second" and mapping.unit not in {"minute", "min"}:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} must declare minute/min for minute_to_second",
                code="UNIT_AMBIGUOUS",
            )
        if mapping.transform != "minute_to_second" and mapping.unit not in {"second", "s"}:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} must prove the retention-time unit",
                code="UNIT_AMBIGUOUS",
            )
    if mapping.transform in {"semicolon_split", "first_semicolon_value"} and mapping.value_kind != "string":
        raise DeclarativePlanError(f"mapping {mapping.mapping_id} uses a string transform on a non-string value")
    if mapping.transform == "plus_marker_to_bool" and mapping.value_kind != "boolean":
        raise DeclarativePlanError(f"mapping {mapping.mapping_id} must use boolean value_kind")


def _validate_target_shape(mapping: FieldMapping) -> None:
    target = (mapping.target_entity, mapping.target_field)
    if target in _LIST_TARGETS:
        if mapping.value_kind != "string" or mapping.transform not in {"semicolon_split", "singleton_list"}:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} must use string + semicolon_split or singleton_list for a list target"
            )
        return
    if target in _INTEGER_TARGETS and (
        mapping.value_kind != "integer" or mapping.transform != "identity"
    ):
        raise DeclarativePlanError(
            f"mapping {mapping.mapping_id} must use integer + identity for this target"
        )
    if target in _FLOAT_TARGETS:
        allowed = {"identity", "minute_to_second"} if target == ("identification", "rt_seconds") else {"identity"}
        if mapping.value_kind != "float" or mapping.transform not in allowed:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} must use a registered float transform for this target"
            )
    if target in _BOOLEAN_TARGETS and (
        mapping.value_kind != "boolean" or mapping.transform not in {"identity", "plus_marker_to_bool"}
    ):
        raise DeclarativePlanError(
            f"mapping {mapping.mapping_id} must use a registered boolean transform for this target"
        )
    if target not in _LIST_TARGETS | _INTEGER_TARGETS | _FLOAT_TARGETS | _BOOLEAN_TARGETS:
        allowed = {"identity", "trim", "first_semicolon_value"}
        if target == ("protein", "accession") or target == ("modification", "name"):
            allowed.add("semicolon_split")
        if mapping.value_kind not in {"string", "integer"} or mapping.transform not in allowed:
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} has an incompatible scalar value shape"
            )


def _validate_observed_delimiter(
    path: Path,
    source: DeclarativeSource,
    mapping: FieldMapping,
) -> None:
    target = (mapping.target_entity, mapping.target_field)
    required_transform = {
        ("protein", "accession"): "semicolon_split",
        ("protein_group", "leading_accession"): "first_semicolon_value",
        ("modification", "name"): "semicolon_split",
    }.get(target)
    if (
        required_transform is None
        or mapping.transform == required_transform
        or not _field_contains_semicolon(path, source, mapping.source_field)
    ):
        return
    raise DeclarativePlanError(
        f"mapping {mapping.mapping_id} observed semicolon-delimited values and must use "
        f"{required_transform} for {mapping.target_entity}.{mapping.target_field}",
        code="SCIENTIFIC_SEMANTIC_UNKNOWN",
    )


def _field_contains_semicolon(path: Path, source: DeclarativeSource, field_name: str) -> bool:
    if source.reader == "delimited":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return any(
                ";" in str(row.get(field_name) or "")
                for row in csv.DictReader(stream, delimiter=source.delimiter or "\t")
            )
    if source.reader == "jsonl":
        with path.open("r", encoding="utf-8-sig") as stream:
            return any(
                ";" in str(value.get(field_name) or "")
                for line in stream
                if line.strip()
                for value in [json.loads(line)]
                if isinstance(value, dict)
            )
    if source.reader == "parquet":
        parquet = pq.ParquetFile(path)
        return any(
            ";" in str(value or "")
            for batch in parquet.iter_batches(columns=[field_name], batch_size=4096)
            for value in batch.column(0).to_pylist()
        )
    return False


def _require_bottom_up_identity(plan: DeclarativeImportPlan, sources: dict[str, DeclarativeSource]) -> None:
    del sources
    targets = {(item.target_entity, item.target_field) for item in plan.field_mappings}
    if ("peptide", "sequence") not in targets:
        raise DeclarativePlanError("BOTTOM_UP plans require a mapped peptide.sequence")
    by_source: dict[str, set[tuple[str, str]]] = {}
    for item in plan.field_mappings:
        by_source.setdefault(item.source_id, set()).add((item.target_entity, item.target_field))
    identification_identity = {
        ("identification", "source_id"),
        ("run", "name"),
        ("peptide", "sequence"),
    }
    for source_id, source_targets in by_source.items():
        source = next(s for s in plan.sources if s.source_id == source_id)
        if source.identification_identity == "source_row":
            if ("identification", "source_id") in source_targets:
                raise DeclarativePlanError("source_row identity cannot also map identification.source_id")
            source_targets.add(("identification", "source_id"))
        if any(entity == "identification" for entity, _field in source_targets):
            missing = identification_identity - source_targets
            if missing:
                labels = ", ".join(sorted(f"{entity}.{field}" for entity, field in missing))
                raise DeclarativePlanError(
                    f"identification source {source_id} requires same-row identity mappings: {labels}"
                )
        protein_fields = {field for entity, field in source_targets if entity == "protein"}
        if protein_fields and not (
            ("protein", "accession") in source_targets
            or ("identification", "protein_accessions") in source_targets
        ):
            raise DeclarativePlanError(
                f"protein source {source_id} requires protein.accession or identification.protein_accessions"
            )
        if any(entity == "protein_group" for entity, _field in source_targets) and (
            "protein_group",
            "source_id",
        ) not in source_targets:
            raise DeclarativePlanError(
                f"protein-group source {source_id} requires protein_group.source_id"
            )
        quant_fields = {field for entity, field in source_targets if entity == "quantification"}
        if quant_fields and "value" not in quant_fields:
            raise DeclarativePlanError(
                f"quantification source {source_id} requires quantification.value"
            )


def _inventory_paths(root: Path) -> set[str]:
    service = InventoryService(root)
    cursor: str | None = None
    paths: set[str] = set()
    while True:
        page = service.list_files(limit=1_000, cursor=cursor)
        paths.update(item.relative_path for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            return paths


def _require_identification_row_mappings(
    plan: DeclarativeImportPlan,
    source_id: str,
    *,
    feature: str,
) -> None:
    targets = {
        (item.target_entity, item.target_field)
        for item in plan.field_mappings
        if item.source_id == source_id
    }
    required = {
        ("identification", "source_id"),
        ("run", "name"),
        ("peptide", "sequence"),
    }
    if not required.issubset(targets):
        source = next(s for s in plan.sources if s.source_id == source_id)
        if source.identification_identity == "source_row":
            targets.add(("identification", "source_id"))
    if not required.issubset(targets):
        raise DeclarativePlanError(
            f"{feature} mappings require identification, run, and peptide identity in the same source row"
        )


def _validate_evidence_bindings(
    plan: DeclarativeImportPlan,
    trusted_observations: Mapping[str, dict[str, Any]],
) -> None:
    referenced = {
        reference
        for collection in (
            plan.field_mappings,
            plan.join_rules,
            plan.asset_dispositions,
        )
        for item in collection
        for reference in item.evidence_refs
    }
    for source in plan.sources:
        referenced.update(source.accession_rule_evidence_refs)
    referenced.update(plan.acquisition_mode_evidence_refs)
    missing = sorted(referenced - set(trusted_observations))
    if missing:
        raise DeclarativePlanError(
            "plan evidence_refs are not backed by Agent 1 observations: " + ", ".join(missing),
            code="SCIENTIFIC_SEMANTIC_UNKNOWN",
        )
    sources = {item.source_id: item for item in plan.sources}
    for source in plan.sources:
        mappings = [item for item in plan.field_mappings if item.source_id == source.source_id]
        actual_targets = {(item.source_field, f"{item.target_entity}.{item.target_field}") for item in mappings}
        for observation in trusted_observations.values():
            facts = observation.get("facts") or {}
            if observation.get("relative_path") != source.relative_path or facts.get("profile") != "maxquant-reported-table-v1":
                continue
            for field, target in facts.get("required_field_targets", {}).items():
                if target.startswith("quantification.") and not any(item.target_entity == "quantification" and item.target_field == "value" for item in mappings):
                    continue
                if _observation_supports_field(observation, source.relative_path, field) and (field, target) not in actual_targets:
                    raise DeclarativePlanError(f"registered source semantics require {field} -> {target}; retaining the raw field alone does not preserve this supported association/label")
    for mapping in plan.field_mappings:
        source = sources[mapping.source_id]
        observations = [trusted_observations[item] for item in mapping.evidence_refs]
        for observation in observations:
            facts = observation.get("facts") or {}
            if observation.get("relative_path") == source.relative_path and facts.get("profile") in {"diaclip-fdr-reader-v1", "maxquant-reported-table-v1"}:
                if mapping.target_entity == "quantification" and mapping.measurement_name is not None and facts.get("labelled_channels") is False:
                    raise DeclarativePlanError("this source has no labelled channel; measurement_name is a channel label, not a metric/display name; omit it and preserve the original metric", code="SCIENTIFIC_SEMANTIC_UNKNOWN")
                if mapping.required and facts.get("missing_value_counts", {}).get(mapping.source_field, 0):
                    raise DeclarativePlanError("required mapping has missing values in the full source; preserve absent optional facts without dropping their records", code="ADAPTER_FIELD_MAPPING_FAILED")
                allowed_targets = facts.get("field_targets", {}).get(mapping.source_field)
                if allowed_targets is not None and f"{mapping.target_entity}.{mapping.target_field}" not in allowed_targets:
                    raise DeclarativePlanError("mapping changes the registered source field's entity scope", code="SCIENTIFIC_SEMANTIC_UNKNOWN")
                transforms = facts.get("target_transforms", {}).get(f"{mapping.source_field}:{mapping.target_entity}.{mapping.target_field}")
                if transforms is not None and mapping.transform not in transforms:
                    raise DeclarativePlanError("mapping transform contradicts the registered source contract", code="SCIENTIFIC_SEMANTIC_UNKNOWN")
                if (mapping.target_entity, mapping.target_field) == ("identification", "source_id") and mapping.source_field == "Precursor.Id" and facts.get("duplicate_run_precursor_ids", 0):
                    raise DeclarativePlanError("Precursor.Id is duplicated in this complete source; use identification_identity=source_row and retain Precursor.Id in source_fields", code="REFERENCE_INTEGRITY_FAILED")
        if not any(
            _observation_supports_field(item, source.relative_path, mapping.source_field)
            for item in observations
        ):
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} has no field-level observation evidence",
                code="SCIENTIFIC_SEMANTIC_UNKNOWN",
            )
        if mapping.target_field == "rt_seconds" and not any(
            _observation_supports_unit(
                item,
                source.relative_path,
                mapping.source_field,
                mapping.unit,
            )
            for item in observations
        ):
            raise DeclarativePlanError(
                f"mapping {mapping.mapping_id} has no observation that proves its retention-time unit; "
                f'require exact confirmation "confirm unit:{mapping.source_field}={mapping.unit}"',
                code="UNIT_AMBIGUOUS",
            )
    for source in plan.sources:
        if source.fasta_accession_rule != "uniprot_pipe_accession":
            continue
        if not any(
            _observation_proves_uniprot_fasta(trusted_observations[item], source.relative_path)
            for item in source.accession_rule_evidence_refs
        ):
            raise DeclarativePlanError(
                f"FASTA source {source.source_id} lacks evidence for UniProt pipe accession parsing",
                code="SCIENTIFIC_SEMANTIC_UNKNOWN",
            )
    for disposition in plan.asset_dispositions:
        if not any(
            _observation_is_for_path(trusted_observations[item], disposition.relative_path)
            for item in disposition.evidence_refs
        ):
            raise DeclarativePlanError(
                f"asset disposition for {disposition.relative_path} lacks a path-specific observation",
                code="SCIENTIFIC_SEMANTIC_UNKNOWN",
            )
    if plan.acquisition_mode is not None and not any(
        _observation_supports_acquisition_mode(
            trusted_observations[item],
            plan.acquisition_mode,
        )
        for item in plan.acquisition_mode_evidence_refs
    ):
        raise DeclarativePlanError(
            "declared mzML acquisition_mode is not supported by trusted evidence; "
            f'require exact confirmation "confirm acquisition_mode={plan.acquisition_mode}"',
            code="SCIENTIFIC_SEMANTIC_UNKNOWN",
        )


def _observation_supports_field(
    observation: dict[str, Any],
    relative_path: str,
    field_name: str,
) -> bool:
    if observation.get("relative_path") != relative_path:
        return False
    facts = observation.get("facts")
    if isinstance(facts, dict):
        raw_fields = list(facts.get("columns") or []) + list(facts.get("fields") or [])
    else:
        raw_fields = observation.get("header")
        inspected = observation.get("inspected_columns")
        if isinstance(inspected, dict) and field_name in inspected:
            return True
    if not isinstance(raw_fields, list):
        return False
    names = {
        str(item.get("name")) if isinstance(item, dict) else str(item)
        for item in raw_fields
    }
    return field_name in names


def _observation_supports_unit(
    observation: dict[str, Any],
    relative_path: str,
    field_name: str,
    unit: str | None,
) -> bool:
    if observation.get("kind") == "user_input":
        text = str(observation.get("text") or "").strip().casefold()
        expected_units = "(?:minute|min)" if unit in {"minute", "min"} else "(?:second|seconds|s)"
        pattern = rf"^confirm\s+unit:{re.escape(field_name.casefold())}\s*=\s*{expected_units}$"
        return re.fullmatch(pattern, text) is not None
    if not _observation_supports_field(observation, relative_path, field_name) or unit is None:
        return False
    facts = observation.get("facts")
    assert isinstance(facts, dict)
    raw_fields = list(facts.get("columns") or []) + list(facts.get("fields") or [])
    for item in raw_fields if isinstance(raw_fields, list) else []:
        if not isinstance(item, dict) or item.get("name") != field_name:
            continue
        declared = item.get("unit")
        aliases = (
            {"minute", "min"}
            if unit in {"minute", "min"}
            else {"second", "seconds", "s"}
            if unit in {"second", "s"}
            else {unit.casefold()}
        )
        if isinstance(declared, str) and declared.casefold() in aliases:
            return True
    normalized_name = field_name.casefold().replace(" ", "")
    if unit in {"minute", "min"}:
        return any(token in normalized_name for token in ("[min]", "(min)", "_min", ".min"))
    if unit in {"second", "s"}:
        return any(token in normalized_name for token in ("[s]", "(s)", "_seconds", ".seconds"))
    return False


def _observation_proves_uniprot_fasta(observation: dict[str, Any], relative_path: str) -> bool:
    if observation.get("relative_path") != relative_path:
        return False
    facts = observation.get("facts")
    if not isinstance(facts, dict):
        return False
    samples = facts.get("identifier_samples")
    return bool(samples) and all(
        isinstance(item, str) and re.match(r"^(?:sp|tr)\|[^|]+\|", item)
        for item in samples
    )


def _observation_is_for_path(observation: dict[str, Any], relative_path: str) -> bool:
    return observation.get("relative_path") == relative_path


def _observation_supports_acquisition_mode(
    observation: dict[str, Any],
    acquisition_mode: str,
) -> bool:
    if observation.get("kind") == "user_input":
        text = str(observation.get("text") or "").strip().casefold()
        return re.fullmatch(
            rf"confirm\s+acquisition_mode\s*=\s*{re.escape(acquisition_mode)}",
            text,
        ) is not None
    facts = observation.get("facts")
    return isinstance(facts, dict) and str(facts.get("acquisition_mode") or "").casefold() == acquisition_mode
