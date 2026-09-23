"""Execute a validated Bottom-Up mapping with fixed, non-code primitives."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .contracts import DeclarativeImportPlan, DeclarativeSource, FieldMapping
from .preflight import DeclarativePlanError, preflight_declarative_plan
from .semantic_schema import (
    SemanticDataset,
    SemanticAssetDisposition,
    SemanticIdentification,
    SemanticModification,
    SemanticPeptide,
    SemanticProtein,
    SemanticProteinGroup,
    SemanticQuantification,
    SemanticRelationship,
    SemanticRun,
    SemanticSourceFile,
)


class DeclarativeExecutionError(ValueError):
    def __init__(self, message: str, *, code: str = "DECLARATIVE_EXECUTION_FAILED") -> None:
        self.code = code
        super().__init__(message)


def execute_plan_to_semantic_dataset(
    *,
    source_root: str | Path,
    source_fingerprint: str,
    plan: DeclarativeImportPlan,
) -> SemanticDataset:
    root = Path(source_root).resolve(strict=True)
    preflight_declarative_plan(source_root=root, plan=plan)
    plan_sha256 = hashlib.sha256(
        plan.model_dump_json(exclude_none=False).encode("utf-8")
    ).hexdigest()
    source_files = [_source_identity(root, item) for item in plan.sources if _source_path(root, item).is_file()]
    mappings_by_source: dict[str, list[FieldMapping]] = defaultdict(list)
    for mapping in plan.field_mappings:
        mappings_by_source[mapping.source_id].append(mapping)
    accounted_fields = _accounted_fields(plan)

    runs: dict[str, dict[str, Any]] = {}
    identifications: dict[str, dict[str, Any]] = {}
    peptides: dict[str, dict[str, Any]] = {}
    proteins: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    quantification: dict[str, dict[str, Any]] = {}
    modifications: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, Any]] = {}

    fasta_sequences, ambiguous_fasta = _fasta_sequences(root, plan.sources)
    for source in plan.sources:
        if source.reader not in {"delimited", "jsonl", "parquet"}:
            continue
        mappings = mappings_by_source.get(source.source_id, [])
        if not mappings:
            continue
        for row_number, row in enumerate(_read_rows(_source_path(root, source), source), 1):
            if any(not isinstance(key, str) for key in row):
                raise DeclarativeExecutionError(
                    f"source {source.source_id} row {row_number} has values outside its declared columns",
                    code="ADAPTER_FIELD_MAPPING_FAILED",
                )
            unexpected = sorted(set(row) - accounted_fields.get(source.source_id, set()))
            if unexpected:
                raise DeclarativeExecutionError(
                    f"source {source.source_id} row {row_number} introduced unaccounted fields: "
                    + ", ".join(unexpected),
                    code="ADAPTER_FIELD_MAPPING_FAILED",
                )
            values = _mapped_values(row, mappings, row_number=row_number)
            _collect_row(
                source=source,
                row_number=row_number,
                row=row,
                values=values,
                runs=runs,
                identifications=identifications,
                peptides=peptides,
                proteins=proteins,
                groups=groups,
                quantification=quantification,
                modifications=modifications,
                relationships=relationships,
            )

    _attach_fasta_sequences(proteins, fasta_sequences, ambiguous_fasta)
    _finalize_relations(identifications, peptides, proteins, groups, relationships)
    dataset = SemanticDataset(
        plan_id=plan.plan_id,
        plan_sha256=plan_sha256,
        source_fingerprint=source_fingerprint,
        source_files=sorted(source_files, key=lambda item: item.relative_path.encode("utf-8")),
        asset_dispositions=[
            SemanticAssetDisposition.model_validate(item.model_dump(mode="json"))
            for item in plan.asset_dispositions
        ],
        runs=[SemanticRun.model_validate(item) for item in _sorted_values(runs)],
        identifications=[SemanticIdentification.model_validate(item) for item in _sorted_values(identifications)],
        peptides=[SemanticPeptide.model_validate(item) for item in _sorted_values(peptides)],
        proteins=[SemanticProtein.model_validate(item) for item in _sorted_values(proteins)],
        protein_groups=[SemanticProteinGroup.model_validate(item) for item in _sorted_values(groups)],
        modifications=[SemanticModification.model_validate(item) for item in _sorted_values(modifications)],
        quantification=[SemanticQuantification.model_validate(item) for item in _sorted_values(quantification)],
        relationships=[SemanticRelationship.model_validate(item) for item in _sorted_values(relationships)],
        requested_view_ids=[item.view_id for item in plan.requested_views],
        unmapped_fields=plan.unmapped_fields,
        warnings=_warnings(plan, proteins, fasta_sequences, ambiguous_fasta),
    )
    _validate_references(dataset)
    return dataset


def _collect_row(
    *,
    source: DeclarativeSource,
    row_number: int,
    row: dict[str, Any],
    values: dict[tuple[str, str], Any],
    runs: dict[str, dict[str, Any]],
    identifications: dict[str, dict[str, Any]],
    peptides: dict[str, dict[str, Any]],
    proteins: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    quantification: dict[str, dict[str, Any]],
    modifications: dict[str, dict[str, Any]],
    relationships: dict[str, dict[str, Any]],
) -> None:
    evidence = sorted(
        {
            ref
            for mapping in values.get(("_meta", "mappings"), [])
            for ref in mapping.evidence_refs
        }
    )
    sequence = _text(values.get(("peptide", "sequence")))
    source_record_id = _text(values.get(("identification", "source_id")))
    run_name = _text(values.get(("run", "name")))
    group_source = _text(values.get(("protein_group", "source_id")))
    accessions = _strings(
        values.get(("identification", "protein_accessions"), values.get(("protein", "accession")))
    )
    source_group_ids = _strings(values.get(("identification", "protein_group_ids")))

    peptide_id: str | None = None
    if sequence:
        peptide_id = _stable_id("peptide", sequence)
        peptide = peptides.setdefault(
            peptide_id,
            {
                "peptide_id": peptide_id,
                "sequence": sequence,
                "identification_ids": [],
                "protein_ids": [],
                "modified_sequences": [],
                "evidence_refs": evidence,
            },
        )
        modified = _text(values.get(("identification", "modified_sequence")))
        if modified and modified not in peptide["modified_sequences"]:
            peptide["modified_sequences"].append(modified)

    run_id: str | None = None
    if run_name:
        run_id = _stable_id("run", run_name)
        runs.setdefault(
            run_id,
            {"run_id": run_id, "name": run_name, "source_file": None, "evidence_refs": evidence},
        )

    protein_ids: list[str] = []
    has_protein_mapping = any(
        entity == "protein" for entity, _field in values if entity not in {"_meta", "_mapping"}
    )
    row_is_preserved_by_parent = bool(source_record_id and run_name and sequence) or bool(group_source)
    for accession in accessions:
        protein_id = _stable_id("protein", accession)
        protein_ids.append(protein_id)
        protein = _upsert_protein(
            proteins,
            {
                "protein_id": protein_id,
                "accession": accession,
                "name": _text(values.get(("protein", "name"))),
                "gene": _text(values.get(("protein", "gene"))),
                "description": _text(values.get(("protein", "description"))),
                "sequence": None,
                "sequence_state": "MISSING",
                "is_decoy": values.get(("protein", "is_decoy")),
                "peptide_ids": [],
                "identification_ids": [],
                "protein_group_ids": [],
                "source_fields": (
                    {source.source_id: _json_safe_row(row)}
                    if has_protein_mapping and not row_is_preserved_by_parent
                    else {}
                ),
                "evidence_refs": evidence,
            },
        )
        if peptide_id:
            _append_unique(protein["peptide_ids"], peptide_id)
            _append_unique(peptides[peptide_id]["protein_ids"], protein_id)
            _put_relationship(
                relationships,
                "peptide_to_protein",
                peptide_id,
                protein_id,
                "DIRECT",
                evidence,
            )

    group_ids: list[str] = []
    for source_group in source_group_ids:
        group_id = _stable_id("protein_group", source_group)
        group_ids.append(group_id)
        groups.setdefault(
            group_id,
            {
                "protein_group_id": group_id,
                "source_group": source_group,
                "member_protein_ids": [],
                "leading_protein_id": None,
                "identification_ids": [],
                "q_value": None,
                "pep": None,
                "source_fields": {},
                "evidence_refs": evidence,
            },
        )

    if group_source:
        group_id = _stable_id("protein_group", group_source)
        members = _strings(values.get(("protein_group", "member_accessions")))
        member_ids = []
        for accession in members:
            protein_id = _stable_id("protein", accession)
            member_ids.append(protein_id)
            _upsert_protein(
                proteins,
                {
                    "protein_id": protein_id,
                    "accession": accession,
                    "name": None,
                    "gene": None,
                    "description": None,
                    "sequence": None,
                    "sequence_state": "MISSING",
                    "is_decoy": None,
                    "peptide_ids": [],
                    "identification_ids": [],
                    "protein_group_ids": [group_id],
                    # The owning protein-group record already preserves this physical row.
                    "source_fields": {},
                    "evidence_refs": evidence,
                },
            )
        leading = _text(values.get(("protein_group", "leading_accession")))
        leading_id = _stable_id("protein", leading) if leading else None
        if leading_id is not None and leading_id not in member_ids:
            raise DeclarativeExecutionError(
                f"protein group {group_source} leading protein is not a declared member",
                code="REFERENCE_INTEGRITY_FAILED",
            )
        groups[group_id] = {
            "protein_group_id": group_id,
            "source_group": group_source,
            "member_protein_ids": member_ids,
            "leading_protein_id": leading_id,
            "identification_ids": groups.get(group_id, {}).get("identification_ids", []),
            "q_value": values.get(("protein_group", "q_value")),
            "pep": values.get(("protein_group", "pep")),
            "source_fields": dict(row),
            "evidence_refs": evidence,
        }

    if not (source_record_id and run_id and peptide_id):
        return
    identification_id = _stable_id("identification", source.source_id, source_record_id)
    if identification_id in identifications:
        raise DeclarativeExecutionError(f"duplicate identification identity at {source.source_id}:{row_number}")
    scan = values.get(("identification", "scan_number"), values.get(("spectrum", "scan_number")))
    identifications[identification_id] = {
        "identification_id": identification_id,
        "source_record_id": source_record_id,
        "run_id": run_id,
        "peptide_id": peptide_id,
        "modified_sequence": _text(values.get(("identification", "modified_sequence"))),
        "charge": values.get(("identification", "charge")),
        "precursor_mz": values.get(("identification", "precursor_mz")),
        "neutral_mass": values.get(("identification", "neutral_mass")),
        "rt_seconds": values.get(("identification", "rt_seconds")),
        "source_scan": scan,
        "source_native_id": _text(values.get(("spectrum", "native_id"))),
        "spectrum_id": None,
        "spectrum_link_state": "MISSING" if scan is not None else "MISSING",
        "score": values.get(("identification", "score")),
        "q_value": values.get(("identification", "q_value")),
        "pep": values.get(("identification", "pep")),
        "protein_ids": protein_ids,
        "protein_group_ids": group_ids,
        "modification_ids": [],
        "quantification_ids": [],
        "source_fields": _json_safe_row(row),
        "evidence_refs": evidence,
    }
    _append_unique(peptides[peptide_id]["identification_ids"], identification_id)
    _put_relationship(
        relationships,
        "identification_to_peptide",
        identification_id,
        peptide_id,
        "DIRECT",
        evidence,
    )
    for protein_id in protein_ids:
        _append_unique(proteins[protein_id]["identification_ids"], identification_id)
        _put_relationship(
            relationships,
            "identification_to_protein",
            identification_id,
            protein_id,
            "DIRECT",
            evidence,
        )
    for group_id in group_ids:
        _append_unique(groups[group_id]["identification_ids"], identification_id)
        _put_relationship(
            relationships,
            "identification_to_protein_group",
            identification_id,
            group_id,
            "DIRECT",
            evidence,
        )

    modification_names = _strings(values.get(("modification", "name")))
    for ordinal, name in enumerate(modification_names, 1):
        if name.casefold() in {"unmodified", "none", "no modification"}:
            continue
        modification_id = _stable_id("modification", identification_id, str(ordinal), name)
        position = values.get(("modification", "position"))
        modifications[modification_id] = {
            "modification_id": modification_id,
            "identification_id": identification_id,
            "peptide_id": peptide_id,
            "name": name,
            "accession": _text(values.get(("modification", "accession"))),
            "mass_shift": values.get(("modification", "mass_shift")),
            "position": position,
            "residue": _text(values.get(("modification", "residue"))),
            "localization_probability": values.get(("modification", "localization_probability")),
            "localization_state": "DIRECT" if position is not None else "MISSING",
            "source_fields": _json_safe_row(row),
            "evidence_refs": evidence,
        }
        identifications[identification_id]["modification_ids"].append(modification_id)

    quant_mappings = [
        mapping
        for mapping in values.get(("_meta", "mappings"), [])
        if mapping.target_entity == "quantification" and mapping.target_field == "value"
    ]
    for quant_mapping in quant_mappings:
        quantification_id = _stable_id(
            "quantification",
            identification_id,
            quant_mapping.mapping_id,
            str(row_number),
        )
        quantification[quantification_id] = {
            "quantification_id": quantification_id,
            "entity_kind": "identification",
            "entity_id": identification_id,
            "run_id": run_id,
            "sample": _text(values.get(("quantification", "sample"))),
            "channel": _text(
                values.get(("quantification", "channel")) or quant_mapping.measurement_name
            ),
            "value": values.get(("_mapping", quant_mapping.mapping_id)),
            "unit": quant_mapping.unit,
            "normalization_kind": _text(values.get(("quantification", "normalization_kind"))),
            "source_fields": {},
            "evidence_refs": evidence,
        }
        identifications[identification_id]["quantification_ids"].append(quantification_id)


def _mapped_values(
    row: dict[str, Any],
    mappings: list[FieldMapping],
    *,
    row_number: int,
) -> dict[tuple[str, str], Any]:
    result: dict[tuple[str, str], Any] = {("_meta", "mappings"): mappings}
    for mapping in mappings:
        raw = row.get(mapping.source_field)
        try:
            converted = _convert(raw, mapping)
            result[(mapping.target_entity, mapping.target_field)] = converted
            result[("_mapping", mapping.mapping_id)] = converted
        except (TypeError, ValueError) as exc:
            raise DeclarativeExecutionError(
                f"mapping {mapping.mapping_id} failed at row {row_number}"
            ) from exc
    return result


def _convert(raw: Any, mapping: FieldMapping) -> Any:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if mapping.required:
            raise ValueError("required source value is missing")
        return None
    value = raw.strip() if isinstance(raw, str) else raw
    if mapping.transform == "trim":
        value = str(value).strip()
    elif mapping.transform == "semicolon_split":
        value = [part.strip() for part in str(value).split(";") if part.strip()]
    elif mapping.transform == "first_semicolon_value":
        value = next((part.strip() for part in str(value).split(";") if part.strip()), None)
    elif mapping.transform == "plus_marker_to_bool":
        value = str(value).strip() == "+"
    if mapping.transform == "semicolon_split":
        return value
    if mapping.value_kind == "string":
        return str(value)
    if mapping.value_kind == "integer":
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer")
        number = int(value)
        if isinstance(value, float) and value != number:
            raise ValueError("fractional value is not an integer")
        return number
    if mapping.value_kind == "float":
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("numeric value must be finite")
        return number * 60.0 if mapping.transform == "minute_to_second" else number
    if mapping.value_kind == "boolean":
        if isinstance(value, bool):
            return value
        token = str(value).strip().casefold()
        if token in {"true", "1", "yes"}:
            return True
        if token in {"false", "0", "no"}:
            return False
        raise ValueError("value is not a supported boolean token")
    raise ValueError("unsupported value kind")


def _read_rows(path: Path, source: DeclarativeSource) -> Iterator[dict[str, Any]]:
    if source.reader == "delimited":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream, delimiter=source.delimiter or "\t")
        return
    if source.reader == "jsonl":
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DeclarativeExecutionError(f"JSONL row {line_no} is not an object")
                yield value
        return
    if source.reader == "parquet":
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4096):
            yield from batch.to_pylist()
        return
    raise DeclarativeExecutionError(f"source {source.source_id} is not a tabular reader")


def _fasta_sequences(
    root: Path,
    sources: list[DeclarativeSource],
) -> tuple[dict[str, str], set[str]]:
    sequences: dict[str, str] = {}
    ambiguous: set[str] = set()
    for source in sources:
        if source.reader != "fasta":
            continue
        current: str | None = None
        parts: list[str] = []
        path = _source_path(root, source)
        if not path.is_file():
            if source.required:
                raise DeclarativeExecutionError(f"required FASTA source is missing: {source.source_id}")
            continue
        with path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                text = line.strip()
                if not text:
                    continue
                if text.startswith(">"):
                    if current is not None:
                        _store_fasta(
                            sequences,
                            ambiguous,
                            current,
                            "".join(parts),
                            accession_rule=source.fasta_accession_rule or "first_token",
                        )
                    current = text[1:].split(maxsplit=1)[0]
                    parts = []
                elif current is not None:
                    parts.append(text)
        if current is not None:
            _store_fasta(
                sequences,
                ambiguous,
                current,
                "".join(parts),
                accession_rule=source.fasta_accession_rule or "first_token",
            )
    return sequences, ambiguous


def _store_fasta(
    sequences: dict[str, str],
    ambiguous: set[str],
    accession: str,
    sequence: str,
    *,
    accession_rule: str,
) -> None:
    aliases = {accession}
    if accession_rule == "uniprot_pipe_accession":
        pieces = accession.split("|")
        if len(pieces) == 3 and pieces[0] in {"sp", "tr"} and pieces[1]:
            aliases.add(pieces[1])
    for alias in aliases:
        existing = sequences.get(alias)
        if existing is not None and existing != sequence:
            ambiguous.add(alias)
            sequences.pop(alias, None)
        elif alias not in ambiguous:
            sequences[alias] = sequence


def _attach_fasta_sequences(
    proteins: dict[str, dict[str, Any]],
    sequences: dict[str, str],
    ambiguous: set[str],
) -> None:
    for protein in proteins.values():
        accession = protein["accession"]
        if accession in ambiguous:
            protein["sequence_state"] = "AMBIGUOUS"
            continue
        sequence = sequences.get(accession)
        if sequence:
            protein["sequence"] = sequence
            protein["sequence_state"] = "DIRECT"


def _finalize_relations(
    identifications: dict[str, dict[str, Any]],
    peptides: dict[str, dict[str, Any]],
    proteins: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    relationships: dict[str, dict[str, Any]],
) -> None:
    del identifications, peptides
    for group_id, group in groups.items():
        for protein_id in group["member_protein_ids"]:
            if protein_id not in proteins:
                continue
            _append_unique(proteins[protein_id]["protein_group_ids"], group_id)
            _put_relationship(
                relationships,
                "protein_to_protein_group",
                protein_id,
                group_id,
                "DIRECT",
                group["evidence_refs"],
            )
    for collection in (proteins, groups):
        for record in collection.values():
            for key, value in record.items():
                if isinstance(value, list):
                    value.sort()


def _validate_references(dataset: SemanticDataset) -> None:
    ids = {
        "identification": {item.identification_id for item in dataset.identifications},
        "peptide": {item.peptide_id for item in dataset.peptides},
        "protein": {item.protein_id for item in dataset.proteins},
        "protein_group": {item.protein_group_id for item in dataset.protein_groups},
    }
    for identification in dataset.identifications:
        if identification.peptide_id not in ids["peptide"]:
            raise DeclarativeExecutionError("identification references a missing peptide")
        if not set(identification.protein_ids).issubset(ids["protein"]):
            raise DeclarativeExecutionError("identification references a missing protein")
        if not set(identification.protein_group_ids).issubset(ids["protein_group"]):
            raise DeclarativeExecutionError("identification references a missing protein group")
        if not set(identification.modification_ids).issubset(
            {item.modification_id for item in dataset.modifications}
        ):
            raise DeclarativeExecutionError("identification references a missing modification")


def _source_path(root: Path, source: DeclarativeSource) -> Path:
    return root.joinpath(*Path(source.relative_path).parts).resolve(strict=False)


def _source_identity(root: Path, source: DeclarativeSource) -> SemanticSourceFile:
    path = _source_path(root, source)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SemanticSourceFile(
        source_id=source.source_id,
        relative_path=source.relative_path,
        role=source.role,
        reader=source.reader,
        size_bytes=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


def _warnings(
    plan: DeclarativeImportPlan,
    proteins: dict[str, dict[str, Any]],
    fasta_sequences: dict[str, str],
    ambiguous_fasta: set[str],
) -> list[str]:
    warnings: list[str] = []
    has_fasta = any(item.reader == "fasta" for item in plan.sources)
    if proteins and not has_fasta:
        warnings.append("REFERENCE_SEQUENCE_MISSING: protein accessions are available but no FASTA was supplied")
    missing = sum(item.get("sequence_state") == "MISSING" for item in proteins.values())
    if has_fasta and missing:
        warnings.append(f"REFERENCE_SEQUENCE_PARTIAL: {missing} protein accessions have no FASTA sequence")
    if ambiguous_fasta:
        warnings.append(f"REFERENCE_SEQUENCE_AMBIGUOUS: {len(ambiguous_fasta)} FASTA identifiers are ambiguous")
    if not any(item.reader == "mzml" for item in plan.sources):
        warnings.append("SPECTRUM_SOURCE_MISSING: identifications cannot open raw spectra")
    if not any(item.target_entity == "modification" for item in plan.field_mappings):
        warnings.append("FRAGMENT_ANNOTATION_MISSING: no source modification/fragment mapping was declared")
    del fasta_sequences
    return warnings


def _put_relationship(
    output: dict[str, dict[str, Any]],
    kind: str,
    left_id: str,
    right_id: str | None,
    state: str,
    evidence_refs: Iterable[str],
) -> None:
    relationship_id = _stable_id("relationship", kind, left_id, right_id or state)
    output.setdefault(
        relationship_id,
        {
            "relationship_id": relationship_id,
            "kind": kind,
            "left_id": left_id,
            "right_id": right_id,
            "state": state,
            "evidence_refs": sorted(set(evidence_refs)),
        },
    )


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join((kind, *parts)).encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{digest}"


def _accounted_fields(plan: DeclarativeImportPlan) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {item.source_id: set() for item in plan.sources}
    for item in plan.field_mappings:
        result[item.source_id].add(item.source_field)
    for item in plan.join_rules:
        result[item.left_source_id].add(item.left_field)
        result[item.right_source_id].add(item.right_field)
    for source_id, fields in plan.unmapped_fields.items():
        result[source_id].update(fields)
    return result


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := _text(item))]
    text = _text(value)
    return [text] if text else []


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _upsert_protein(
    proteins: dict[str, dict[str, Any]],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    protein_id = str(candidate["protein_id"])
    existing = proteins.get(protein_id)
    if existing is None:
        proteins[protein_id] = candidate
        return candidate
    for field in ("accession", "name", "gene", "description", "is_decoy"):
        incoming = candidate.get(field)
        current = existing.get(field)
        if incoming is None:
            continue
        if current is not None and current != incoming:
            raise DeclarativeExecutionError(
                f"conflicting protein {field} values for {existing.get('accession')}",
                code="REFERENCE_INTEGRITY_FAILED",
            )
        existing[field] = incoming
    for field in ("peptide_ids", "identification_ids", "protein_group_ids", "evidence_refs"):
        for value in candidate.get(field, []):
            _append_unique(existing[field], value)
    for source_id, source_row in candidate.get("source_fields", {}).items():
        current = existing["source_fields"].get(source_id)
        if current is not None and current != source_row:
            raise DeclarativeExecutionError(
                f"conflicting protein source rows for {existing.get('accession')}",
                code="REFERENCE_INTEGRITY_FAILED",
            )
        existing["source_fields"][source_id] = source_row
    return existing


def _sorted_values(values: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [values[key] for key in sorted(values)]


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = {str(key): value for key, value in row.items()}
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DeclarativeExecutionError("source row contains a non-canonical JSON value") from exc
    return payload
