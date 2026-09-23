"""Trusted writer bridge for a validated declarative semantic dataset."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.zp_runtime.package import ensure_binary_layer_importable

from .contracts import DeclarativeImportPlan
from .executor import DeclarativeExecutionError, execute_plan_to_semantic_dataset
from .semantic_schema import (
    SEMANTIC_EXTENSION_TYPE,
    SemanticDataset,
    SemanticIdentification,
    SemanticRelationship,
    parse_semantic_extension_payload,
    semantic_extension_payload,
)


@dataclass(frozen=True, slots=True)
class DeclarativeZpArtifact:
    path: Path
    output_sha256: str
    format_version: int
    validation_mode: str
    certificate_path: Path
    semantic_dataset: SemanticDataset
    semantic_verification: dict[str, Any]


def build_declarative_zp_artifact(
    *,
    source_root: str | Path,
    source_fingerprint: str,
    plan: DeclarativeImportPlan,
    output_path: str | Path,
) -> DeclarativeZpArtifact:
    root = Path(source_root).resolve(strict=True)
    target = Path(output_path).resolve(strict=False)
    if target.suffix.casefold() != ".zp":
        raise DeclarativeExecutionError("declarative output path must use the .zp extension")
    if target.exists():
        raise DeclarativeExecutionError("declarative output path already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.stem}.partial.zp")
    certificate = target.with_name(f"{target.stem}.deep-validation.json")
    if partial.exists() or certificate.exists():
        raise DeclarativeExecutionError("declarative Case output paths are not clean")

    semantic = execute_plan_to_semantic_dataset(
        source_root=root,
        source_fingerprint=source_fingerprint,
        plan=plan,
    )
    try:
        blocks, semantic = _build_blocks(root, plan, semantic)
        ensure_binary_layer_importable()
        from binary_layer import ExtensionBlock, ZpWriter, validate_zp  # type: ignore[import-not-found]

        blocks.extensions.append(
            ExtensionBlock(
                extension_type=SEMANTIC_EXTENSION_TYPE,
                extension_version="1",
                payload=semantic_extension_payload(semantic),
            )
        )
        ZpWriter().write(partial, blocks, format_version=3)
        validation = validate_zp(partial, mode="deep", certificate_path=certificate)
        if not validation.valid:
            codes = ", ".join(item.code for item in validation.issues)
            raise DeclarativeExecutionError(f"declarative ZP failed deep validation: {codes}")
        readback = read_semantic_zp(partial)
        if readback != semantic:
            raise DeclarativeExecutionError("semantic ZP readback differs from the executed plan")
        os.link(partial, target)
        partial.unlink()
        output_sha256 = _sha256(target)
        if validation.file_sha256 and output_sha256 != validation.file_sha256:
            raise DeclarativeExecutionError("deep-validation identity differs from committed ZP")
        verification = semantic_verification_summary(readback)
        return DeclarativeZpArtifact(
            path=target,
            output_sha256=output_sha256,
            format_version=int(validation.version or 3),
            validation_mode=str(validation.mode or "deep"),
            certificate_path=certificate,
            semantic_dataset=readback,
            semantic_verification=verification,
        )
    except Exception:
        partial.unlink(missing_ok=True)
        if not target.exists():
            certificate.unlink(missing_ok=True)
        raise


def read_semantic_zp(path: str | Path) -> SemanticDataset:
    ensure_binary_layer_importable()
    from binary_layer import ZpReader  # type: ignore[import-not-found]

    reader = ZpReader(Path(path))
    matches = [
        item for item in reader.read_extensions() if item.extension_type == SEMANTIC_EXTENSION_TYPE
    ]
    if len(matches) != 1 or matches[0].extension_version != "1":
        raise DeclarativeExecutionError("ZP must contain exactly one supported semantic extension")
    try:
        dataset = parse_semantic_extension_payload(matches[0].payload)
    except (TypeError, ValueError) as exc:
        raise DeclarativeExecutionError("semantic extension failed strict readback validation") from exc
    _validate_semantic_links(dataset, reader)
    return dataset


def semantic_verification_summary(dataset: SemanticDataset) -> dict[str, Any]:
    spectrum_states: dict[str, int] = {}
    sequence_states: dict[str, int] = {}
    for item in dataset.identifications:
        spectrum_states[item.spectrum_link_state] = spectrum_states.get(item.spectrum_link_state, 0) + 1
    for item in dataset.proteins:
        sequence_states[item.sequence_state] = sequence_states.get(item.sequence_state, 0) + 1
    return {
        "schema_version": 1,
        "status": "PASSED",
        "plan_id": dataset.plan_id,
        "plan_sha256": dataset.plan_sha256,
        "source_fingerprint": dataset.source_fingerprint,
        "entity_counts": {
            "runs": len(dataset.runs),
            "identifications": len(dataset.identifications),
            "peptides": len(dataset.peptides),
            "proteins": len(dataset.proteins),
            "protein_groups": len(dataset.protein_groups),
            "modifications": len(dataset.modifications),
            "quantification": len(dataset.quantification),
        },
        "spectrum_link_states": spectrum_states,
        "protein_sequence_states": sequence_states,
        "warnings": list(dataset.warnings),
    }


def _build_blocks(root: Path, plan: DeclarativeImportPlan, semantic: SemanticDataset) -> tuple[Any, SemanticDataset]:
    mzml_sources = [
        item
        for item in plan.sources
        if item.reader == "mzml"
        and root.joinpath(*Path(item.relative_path).parts).resolve(strict=False).is_file()
    ]
    if len(mzml_sources) > 1:
        raise DeclarativeExecutionError("the first declarative Bottom-Up version supports at most one mzML source")
    if not mzml_sources:
        return _empty_core_blocks(semantic), semantic

    source = mzml_sources[0]
    if plan.acquisition_mode is None:
        raise DeclarativeExecutionError(
            "mzML execution requires a validated acquisition_mode",
            code="SCIENTIFIC_SEMANTIC_UNKNOWN",
        )
    source_path = root.joinpath(*Path(source.relative_path).parts).resolve(strict=True)
    ensure_binary_layer_importable()
    from binary_layer.mzml_adapter import parse_mzml  # type: ignore[import-not-found]
    from binary_layer.tools.real_mzml import build_mzml_candidate  # type: ignore[import-not-found]

    digest = _sha256(source_path)
    created_at = datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
    document = parse_mzml(source_path)
    blocks = build_mzml_candidate(
        document,
        digest,
        created_at=created_at,
        source_file_label=source.relative_path,
        acquisition_mode=plan.acquisition_mode,
        source_type="viewer_declarative_bottom_up",
        source_file_name=source.relative_path,
        notes=["Generated by Viewer's validated declarative ingestion engine."],
        compact_arrays=True,
    )
    _complete_core_indexes(blocks)
    linked = _link_identifications_to_spectra(plan, semantic, blocks)
    return blocks, linked.model_copy(
        update={
            "core_spectrum_count": len(blocks.spectra),
            "core_chromatogram_count": len(blocks.chromatograms),
        }
    )


def _empty_core_blocks(semantic: SemanticDataset) -> Any:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        BlockCollection,
        GlobalMetaBlock,
        IndexBlock,
        StringPoolBlock,
    )

    aggregate = hashlib.sha256()
    for source in semantic.source_files:
        aggregate.update(source.relative_path.encode("utf-8"))
        aggregate.update(bytes.fromhex(source.sha256))
    return BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=3,
            source_type="viewer_declarative_bottom_up",
            source_file_name=semantic.source_files[0].relative_path if semantic.source_files else "semantic-dataset",
            source_file_hash=aggregate.hexdigest(),
            run_count=0,
            spectrum_count=0,
            chromatogram_count=0,
            array_count=0,
            created_at=datetime.now(timezone.utc),
            generator_name="Viewer Declarative Ingest",
            generator_version="1",
            notes=["No spectrum source was supplied; semantic entities remain available."],
        ),
        string_pool=StringPoolBlock([]),
        indexes=IndexBlock(scan_index=[], rt_index=[], spectrum_id_index=[]),
    )


def _complete_core_indexes(blocks: Any) -> None:
    ensure_binary_layer_importable()
    from binary_layer import IndexBlock, StringPoolBlock  # type: ignore[import-not-found]

    strings: list[str] = []
    for run in blocks.runs:
        strings.extend((run.source_file, run.run_name))
    strings.extend(item.native_id for item in blocks.spectra)
    for item in blocks.chromatograms:
        strings.extend((item.chromatogram_type, item.native_id))
    blocks.string_pool = StringPoolBlock(list(dict.fromkeys(strings)))
    blocks.indexes = IndexBlock(
        scan_index=[
            {"scan_number": item.scan_number, "spectrum_id": item.spectrum_id}
            for item in sorted(blocks.spectra, key=lambda value: value.scan_number)
        ],
        rt_index=[
            {"rt": item.rt, "spectrum_id": item.spectrum_id}
            for item in sorted(blocks.spectra, key=lambda value: value.rt)
        ],
        spectrum_id_index=[
            {"spectrum_id": item.spectrum_id, "position": position}
            for position, item in enumerate(blocks.spectra)
        ],
    )


def _link_identifications_to_spectra(
    plan: DeclarativeImportPlan,
    semantic: SemanticDataset,
    blocks: Any,
) -> SemanticDataset:
    rules = [item for item in plan.join_rules if item.relationship == "identification_to_spectrum"]
    if not rules:
        updated = [
            item.model_copy(
                update={
                    "spectrum_link_state": "AMBIGUOUS" if item.source_scan is not None else "MISSING"
                }
            )
            for item in semantic.identifications
        ]
        return semantic.model_copy(update={"identifications": updated})
    if len(rules) != 1 or rules[0].transform != "identity":
        raise DeclarativeExecutionError("spectrum linking requires one exact identity join")
    rule = rules[0]
    identification_sources = {
        item.source_id
        for item in plan.field_mappings
        if item.target_entity == "identification" and item.target_field == "source_id"
    }
    right_sources = [
        item
        for item in plan.sources
        if item.source_id == rule.right_source_id and item.reader == "mzml"
    ]
    semantic_right_sources = [
        item
        for item in semantic.source_files
        if item.source_id == rule.right_source_id and item.reader == "mzml"
    ]
    if (
        identification_sources != {rule.left_source_id}
        or len(right_sources) != 1
        or len(semantic_right_sources) != 1
    ):
        raise DeclarativeExecutionError(
            "spectrum join source identity is not uniquely determined",
            code="RUN_ASSOCIATION_AMBIGUOUS",
        )
    if len(semantic.runs) != 1 or len(blocks.runs) != 1:
        raise DeclarativeExecutionError(
            "spectrum linking currently requires exactly one semantic run and one core run",
            code="RUN_ASSOCIATION_AMBIGUOUS",
        )
    semantic_run = semantic.runs[0]
    core_run = blocks.runs[0]
    expected_source_file = right_sources[0].relative_path
    semantic_source = semantic_right_sources[0]
    if (
        semantic_source.relative_path != expected_source_file
        or blocks.global_meta is None
        or blocks.global_meta.source_file_hash != semantic_source.sha256
        or core_run.source_file != expected_source_file
        or semantic_run.source_file not in {None, expected_source_file}
        or any(item.run_id != semantic_run.run_id for item in semantic.identifications)
        or any(item.run_id != core_run.run_id for item in blocks.spectra)
    ):
        raise DeclarativeExecutionError(
            "semantic and core run source identities cannot be safely bound",
            code="RUN_ASSOCIATION_AMBIGUOUS",
        )
    semantic = semantic.model_copy(
        update={
            "runs": [
                semantic_run.model_copy(
                    update={
                        "source_file": expected_source_file,
                        "evidence_refs": sorted(
                            {*semantic_run.evidence_refs, *rule.evidence_refs}
                        ),
                    }
                )
            ]
        }
    )
    core_run_id = str(core_run.run_id)
    by_run_scan: dict[tuple[str, int], list[Any]] = {}
    for spectrum in blocks.spectra:
        if spectrum.ms_level == 2:
            by_run_scan.setdefault(
                (str(spectrum.run_id), int(spectrum.scan_number)), []
            ).append(spectrum)
    updated: list[SemanticIdentification] = []
    relationships = list(semantic.relationships)
    missing: list[str] = []
    for item in semantic.identifications:
        candidates = (
            by_run_scan.get((core_run_id, item.source_scan), [])
            if item.source_scan is not None
            else []
        )
        if len(candidates) == 1:
            spectrum = candidates[0]
            if item.source_native_id is not None and item.source_native_id != spectrum.native_id:
                raise DeclarativeExecutionError(
                    f"identification {item.identification_id} conflicts with the core spectrum identity",
                    code="RUN_ASSOCIATION_AMBIGUOUS",
                )
            linked = item.model_copy(
                update={
                    "spectrum_id": spectrum.spectrum_id,
                    "source_native_id": spectrum.native_id,
                    "spectrum_link_state": "DIRECT",
                }
            )
            relationships.append(
                SemanticRelationship(
                    relationship_id=_relationship_id(item.identification_id, spectrum.spectrum_id),
                    kind="identification_to_spectrum",
                    left_id=item.identification_id,
                    right_id=spectrum.spectrum_id,
                    state="DIRECT",
                    evidence_refs=rule.evidence_refs,
                )
            )
            updated.append(linked)
        else:
            state = "AMBIGUOUS" if len(candidates) > 1 else "MISSING"
            updated.append(item.model_copy(update={"spectrum_link_state": state, "spectrum_id": None}))
            missing.append(item.identification_id)
    if rule.cardinality == "one_to_one":
        linked_spectrum_ids = [item.spectrum_id for item in updated if item.spectrum_id]
        if len(linked_spectrum_ids) != len(set(linked_spectrum_ids)):
            raise DeclarativeExecutionError(
                "one-to-one spectrum join maps multiple identifications to one spectrum",
                code="RUN_ASSOCIATION_AMBIGUOUS",
            )
    if missing and rule.on_failure == "BLOCK_DATASET":
        raise DeclarativeExecutionError(
            f"required spectrum relation failed for {len(missing)} identifications",
            code=(
                "RUN_ASSOCIATION_AMBIGUOUS"
                if any(
                    len(by_run_scan.get((core_run_id, item.source_scan), [])) > 1
                    for item in semantic.identifications
                )
                else "REFERENCE_INTEGRITY_FAILED"
            ),
        )
    relationships.sort(key=lambda item: item.relationship_id)
    return semantic.model_copy(update={"identifications": updated, "relationships": relationships})


def _validate_semantic_links(dataset: SemanticDataset, reader: Any) -> None:
    global_meta = reader.read_global_meta()
    raw_runs = reader.read_runs()
    raw_spectra = reader.read_spectra()
    raw_chromatograms = reader.read_chromatograms()
    if dataset.core_spectrum_count != len(raw_spectra):
        raise DeclarativeExecutionError("semantic core_spectrum_count differs from ZP readback")
    if dataset.core_chromatogram_count != len(raw_chromatograms):
        raise DeclarativeExecutionError("semantic core_chromatogram_count differs from ZP readback")
    core_run_ids = {item.run_id for item in raw_runs}
    if len(raw_runs) != len(core_run_ids):
        raise DeclarativeExecutionError("core run identifiers are not unique")
    if any(item.run_id not in core_run_ids for item in raw_spectra):
        raise DeclarativeExecutionError("core spectrum references a missing run")
    spectra_by_id = {item.spectrum_id: item for item in raw_spectra}
    spectra = set(spectra_by_id)
    run_ids = {item.run_id for item in dataset.runs}
    identification_ids = {item.identification_id for item in dataset.identifications}
    peptide_ids = {item.peptide_id for item in dataset.peptides}
    protein_ids = {item.protein_id for item in dataset.proteins}
    group_ids = {item.protein_group_id for item in dataset.protein_groups}
    quantification_ids = {item.quantification_id for item in dataset.quantification}
    modification_ids = {item.modification_id for item in dataset.modifications}
    for label, records, identifiers in (
        ("run", dataset.runs, run_ids),
        ("identification", dataset.identifications, identification_ids),
        ("peptide", dataset.peptides, peptide_ids),
        ("protein", dataset.proteins, protein_ids),
        ("protein group", dataset.protein_groups, group_ids),
        ("quantification", dataset.quantification, quantification_ids),
        ("modification", dataset.modifications, modification_ids),
    ):
        if len(records) != len(identifiers):
            raise DeclarativeExecutionError(f"semantic {label} identifiers are not unique")
    quantification_by_identification: dict[str, set[str]] = {}
    for item in dataset.quantification:
        if item.entity_kind == "identification":
            quantification_by_identification.setdefault(item.entity_id, set()).add(item.quantification_id)
    modifications_by_identification: dict[str, set[str]] = {}
    for item in dataset.modifications:
        if item.identification_id not in identification_ids or item.peptide_id not in peptide_ids:
            raise DeclarativeExecutionError("semantic modification references a missing entity")
        modifications_by_identification.setdefault(item.identification_id, set()).add(item.modification_id)
    for item in dataset.identifications:
        if item.run_id not in run_ids:
            raise DeclarativeExecutionError("semantic identification references a missing run")
        if item.spectrum_id and item.spectrum_id not in spectra:
            raise DeclarativeExecutionError("semantic identification references a missing core spectrum")
        if item.peptide_id not in peptide_ids:
            raise DeclarativeExecutionError("semantic identification references a missing peptide")
        if not set(item.protein_ids).issubset(protein_ids):
            raise DeclarativeExecutionError("semantic identification references a missing protein")
        if not set(item.protein_group_ids).issubset(group_ids):
            raise DeclarativeExecutionError("semantic identification references a missing protein group")
        if not set(item.quantification_ids).issubset(quantification_ids):
            raise DeclarativeExecutionError("semantic identification references missing quantification")
        if set(item.quantification_ids) != quantification_by_identification.get(item.identification_id, set()):
            raise DeclarativeExecutionError("semantic identification quantification links are inconsistent")
        if set(item.modification_ids) != modifications_by_identification.get(item.identification_id, set()):
            raise DeclarativeExecutionError("semantic identification modification links are inconsistent")
    for item in dataset.quantification:
        if item.run_id is not None and item.run_id not in run_ids:
            raise DeclarativeExecutionError("semantic quantification references a missing run")
        valid = {
            "identification": identification_ids,
            "peptide": peptide_ids,
            "protein": protein_ids,
            "protein_group": group_ids,
        }[item.entity_kind]
        if item.entity_id not in valid:
            raise DeclarativeExecutionError("semantic quantification references a missing entity")
    ident_by_id = {item.identification_id: item for item in dataset.identifications}
    for peptide in dataset.peptides:
        if not set(peptide.identification_ids).issubset(identification_ids):
            raise DeclarativeExecutionError("semantic peptide references a missing identification")
        if not set(peptide.protein_ids).issubset(protein_ids):
            raise DeclarativeExecutionError("semantic peptide references a missing protein")
        if any(ident_by_id[item].peptide_id != peptide.peptide_id for item in peptide.identification_ids):
            raise DeclarativeExecutionError("semantic peptide identification links are inconsistent")
    for protein in dataset.proteins:
        if not set(protein.identification_ids).issubset(identification_ids):
            raise DeclarativeExecutionError("semantic protein references a missing identification")
        if not set(protein.peptide_ids).issubset(peptide_ids):
            raise DeclarativeExecutionError("semantic protein references a missing peptide")
        if not set(protein.protein_group_ids).issubset(group_ids):
            raise DeclarativeExecutionError("semantic protein references a missing protein group")
    for group in dataset.protein_groups:
        if not set(group.member_protein_ids).issubset(protein_ids):
            raise DeclarativeExecutionError("semantic protein group references a missing protein")
        if group.leading_protein_id and group.leading_protein_id not in set(group.member_protein_ids):
            raise DeclarativeExecutionError("semantic protein group leading protein is not a member")
        if not set(group.identification_ids).issubset(identification_ids):
            raise DeclarativeExecutionError("semantic protein group references a missing identification")
    relationship_ids = [item.relationship_id for item in dataset.relationships]
    if len(relationship_ids) != len(set(relationship_ids)):
        raise DeclarativeExecutionError("semantic relationship identifiers are not unique")
    endpoints = {
        "identification_to_spectrum": (identification_ids, spectra),
        "identification_to_peptide": (identification_ids, peptide_ids),
        "identification_to_protein": (identification_ids, protein_ids),
        "identification_to_protein_group": (identification_ids, group_ids),
        "peptide_to_protein": (peptide_ids, protein_ids),
        "protein_to_protein_group": (protein_ids, group_ids),
    }
    for relationship in dataset.relationships:
        left_ids, right_ids = endpoints[relationship.kind]
        if relationship.left_id not in left_ids:
            raise DeclarativeExecutionError("semantic relationship has a missing left endpoint")
        if relationship.right_id is not None and relationship.right_id not in right_ids:
            raise DeclarativeExecutionError("semantic relationship has a missing right endpoint")

    array_edges = {
        "identification_to_spectrum": {
            (item.identification_id, item.spectrum_id)
            for item in dataset.identifications
            if item.spectrum_id is not None
        },
        "identification_to_peptide": {
            (item.identification_id, item.peptide_id) for item in dataset.identifications
        },
        "identification_to_protein": {
            (item.identification_id, protein_id)
            for item in dataset.identifications
            for protein_id in item.protein_ids
        },
        "identification_to_protein_group": {
            (item.identification_id, group_id)
            for item in dataset.identifications
            for group_id in item.protein_group_ids
        },
        "peptide_to_protein": {
            (item.peptide_id, protein_id)
            for item in dataset.peptides
            for protein_id in item.protein_ids
        },
        "protein_to_protein_group": {
            (item.protein_id, group_id)
            for item in dataset.proteins
            for group_id in item.protein_group_ids
        },
    }
    reverse_array_edges = {
        "identification_to_peptide": {
            (identification_id, item.peptide_id)
            for item in dataset.peptides
            for identification_id in item.identification_ids
        },
        "identification_to_protein": {
            (identification_id, item.protein_id)
            for item in dataset.proteins
            for identification_id in item.identification_ids
        },
        "identification_to_protein_group": {
            (identification_id, item.protein_group_id)
            for item in dataset.protein_groups
            for identification_id in item.identification_ids
        },
        "peptide_to_protein": {
            (peptide_id, item.protein_id)
            for item in dataset.proteins
            for peptide_id in item.peptide_ids
        },
        "protein_to_protein_group": {
            (protein_id, item.protein_group_id)
            for item in dataset.protein_groups
            for protein_id in item.member_protein_ids
        },
    }
    if any(
        array_edges[kind] != edges for kind, edges in reverse_array_edges.items()
    ):
        raise DeclarativeExecutionError("semantic arrays and relationships are inconsistent")

    available_relationships = [
        item for item in dataset.relationships if item.right_id is not None
    ]
    relationship_edges = {
        (item.kind, item.left_id, item.right_id) for item in available_relationships
    }
    expected_edges = {
        (kind, left_id, right_id)
        for kind, edges in array_edges.items()
        for left_id, right_id in edges
    }
    if len(available_relationships) != len(relationship_edges) or relationship_edges != expected_edges:
        raise DeclarativeExecutionError("semantic arrays and relationships are inconsistent")

    relationship_by_edge = {
        (item.kind, item.left_id, item.right_id): item for item in available_relationships
    }
    for item in dataset.identifications:
        if item.spectrum_id is None:
            continue
        relationship = relationship_by_edge[
            ("identification_to_spectrum", item.identification_id, item.spectrum_id)
        ]
        if (
            relationship.state != item.spectrum_link_state
            or relationship.derivation_id != item.spectrum_link_derivation_id
        ):
            raise DeclarativeExecutionError("semantic arrays and relationships are inconsistent")

    linked_identifications = [
        item for item in dataset.identifications if item.spectrum_id is not None
    ]
    if linked_identifications:
        if len(dataset.runs) != 1 or len(raw_runs) != 1:
            raise DeclarativeExecutionError(
                "linked spectra require exactly one semantic run and one core run",
                code="RUN_ASSOCIATION_AMBIGUOUS",
            )
        semantic_run = dataset.runs[0]
        core_run = raw_runs[0]
        semantic_sources = [
            item
            for item in dataset.source_files
            if item.reader == "mzml" and item.relative_path == core_run.source_file
        ]
        if (
            not core_run.source_file
            or semantic_run.source_file != core_run.source_file
            or len(semantic_sources) != 1
            or semantic_sources[0].sha256 != global_meta.source_file_hash
        ):
            raise DeclarativeExecutionError(
                "linked semantic and core runs do not share a verified source identity",
                code="RUN_ASSOCIATION_AMBIGUOUS",
            )
        for item in linked_identifications:
            spectrum = spectra_by_id[item.spectrum_id]
            if (
                spectrum.run_id != core_run.run_id
                or item.source_scan != spectrum.scan_number
                or item.source_native_id != spectrum.native_id
            ):
                raise DeclarativeExecutionError(
                    "linked identification does not match its bound core spectrum identity",
                    code="RUN_ASSOCIATION_AMBIGUOUS",
                )


def _relationship_id(left_id: str, right_id: str) -> str:
    digest = hashlib.sha256(f"identification_to_spectrum\x1f{left_id}\x1f{right_id}".encode()).hexdigest()[:24]
    return f"relationship:{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
