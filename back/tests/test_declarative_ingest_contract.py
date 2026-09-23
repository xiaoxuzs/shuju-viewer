from __future__ import annotations


def test_join_defaults_match_requiredness_and_explicit_mismatches_are_not_rewritten():
    import pytest
    from app.declarative_ingest.contracts import JoinRule
    base = {"join_id": "scan", "relationship": "identification_to_spectrum", "left_source_id": "rows", "left_field": "scan",
        "right_source_id": "spectra", "right_field": "scan_number", "cardinality": "many_to_one", "evidence_refs": ["source"]}
    assert JoinRule.model_validate(base).on_failure == "BLOCK_DATASET"
    assert JoinRule.model_validate({**base, "required": False}).on_failure == "DISABLE_MODULE"
    with pytest.raises(ValueError, match="BLOCK_DATASET"):
        JoinRule.model_validate({**base, "required": True, "on_failure": "DISABLE_MODULE"})
    with pytest.raises(ValueError, match="DISABLE_MODULE"):
        JoinRule.model_validate({**base, "required": False, "on_failure": "BLOCK_DATASET"})
    assert JoinRule.model_json_schema()["properties"]["on_failure"]["default"] == "BLOCK_DATASET"

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.declarative_ingest import zp_artifact as zp_artifact_module
from app.declarative_ingest import (
    DeclarativeImportPlan,
    DeclarativeExecutionError,
    SemanticDataset,
    build_declarative_zp_artifact,
    execute_plan_to_semantic_dataset,
    preflight_declarative_plan,
    read_semantic_zp,
)
from app.declarative_ingest.preflight import DeclarativePlanError
from app.declarative_ingest.semantic_schema import semantic_extension_payload
from app.zp_runtime.package import ensure_binary_layer_importable


def _write_table(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["record", "sample", "peptide", "rt", "protein", "score", "unused"])
        writer.writerow(["p1", "run-a", "PEPTIDE", "1.5", "P42", "42", "kept-by-source-fields"])


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "plan_id": "unknown-bottom-up-v1",
        "analysis_mode": "BOTTOM_UP",
        "sources": [
            {
                "source_id": "identifications",
                "relative_path": "renamed-results.tsv",
                "role": "identification_table",
                "reader": "delimited",
                "delimiter": "\t",
                "required": True,
                "required_fields": ["record", "sample", "peptide", "rt"],
            }
        ],
        "field_mappings": [
            {
                "mapping_id": "psm-id",
                "source_id": "identifications",
                "source_field": "record",
                "target_entity": "identification",
                "target_field": "source_id",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "run-name",
                "source_id": "identifications",
                "source_field": "sample",
                "target_entity": "run",
                "target_field": "name",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "peptide-sequence",
                "source_id": "identifications",
                "source_field": "peptide",
                "target_entity": "peptide",
                "target_field": "sequence",
                "value_kind": "string",
                "required": True,
                "evidence_refs": ["obs:table"],
            },
            {
                "mapping_id": "retention-time",
                "source_id": "identifications",
                "source_field": "rt",
                "target_entity": "identification",
                "target_field": "rt_seconds",
                "value_kind": "float",
                "required": False,
                "unit": "minute",
                "transform": "minute_to_second",
                "evidence_refs": ["obs:rt-unit"],
            },
        ],
        "unmapped_fields": {"identifications": ["protein", "score", "unused"]},
        "requested_views": [{"view_id": "bu.matches"}],
    }


def _spectrum_link_plan() -> DeclarativeImportPlan:
    payload = _payload()
    payload["acquisition_mode"] = "dda"
    payload["acquisition_mode_evidence_refs"] = ["obs:acquisition"]
    payload["sources"].append(
        {
            "source_id": "spectra",
            "relative_path": "spectra.mzML",
            "role": "spectrum_source",
            "reader": "mzml",
            "required": True,
            "required_fields": [],
        }
    )
    payload["field_mappings"].append(
        {
            "mapping_id": "scan",
            "source_id": "identifications",
            "source_field": "scan",
            "target_entity": "identification",
            "target_field": "scan_number",
            "value_kind": "integer",
            "required": True,
            "evidence_refs": ["obs:scan"],
        }
    )
    payload["join_rules"] = [
        {
            "join_id": "psm-spectrum",
            "relationship": "identification_to_spectrum",
            "left_source_id": "identifications",
            "left_field": "scan",
            "right_source_id": "spectra",
            "right_field": "scan_number",
            "cardinality": "many_to_one",
            "transform": "identity",
            "required": True,
            "on_failure": "BLOCK_DATASET",
            "evidence_refs": ["obs:scan-link"],
        }
    ]
    return DeclarativeImportPlan.model_validate(payload)


def _semantic_for_spectrum_link(*, run_count: int = 1, native_id: str | None = None) -> SemanticDataset:
    runs = [
        {"run_id": f"semantic-run-{index}", "name": f"run-{index}"}
        for index in range(1, run_count + 1)
    ]
    return SemanticDataset.model_validate(
        {
            "plan_id": "spectrum-link-v1",
            "plan_sha256": "1" * 64,
            "source_fingerprint": "2" * 32,
            "source_files": [
                {
                    "source_id": "spectra",
                    "relative_path": "spectra.mzML",
                    "role": "spectrum_source",
                    "reader": "mzml",
                    "size_bytes": 1,
                    "sha256": "3" * 64,
                }
            ],
            "runs": runs,
            "identifications": [
                {
                    "identification_id": "identification:1",
                    "source_record_id": "1",
                    "run_id": "semantic-run-1",
                    "peptide_id": "peptide:1",
                    "source_scan": 7,
                    "source_native_id": native_id,
                    "spectrum_link_state": "MISSING",
                    "source_fields": {},
                }
            ],
            "peptides": [
                {
                    "peptide_id": "peptide:1",
                    "sequence": "PEPTIDE",
                    "identification_ids": ["identification:1"],
                }
            ],
            "relationships": [
                {
                    "relationship_id": "relationship:identification-peptide",
                    "kind": "identification_to_peptide",
                    "left_id": "identification:1",
                    "right_id": "peptide:1",
                    "state": "DIRECT",
                }
            ],
        }
    )


def _core_blocks(
    *,
    run_count: int = 1,
    source_file: str = "spectra.mzML",
    source_sha256: str = "3" * 64,
) -> SimpleNamespace:
    runs = [
        SimpleNamespace(
            run_id=f"core-run-{index}",
            source_file=source_file if index == 1 else f"other-{index}.mzML",
            run_name=f"core-run-{index}",
        )
        for index in range(1, run_count + 1)
    ]
    spectra = [
        SimpleNamespace(
            spectrum_id=f"spectrum:{index}",
            run_id=run.run_id,
            ms_level=2,
            scan_number=7 if index == 1 else 7 + index,
            native_id=f"controllerType=0 controllerNumber=1 scan={7 if index == 1 else 7 + index}",
        )
        for index, run in enumerate(runs, 1)
    ]
    return SimpleNamespace(
        global_meta=SimpleNamespace(source_file_hash=source_sha256),
        runs=runs,
        spectra=spectra,
    )


def _write_semantic_only_zp(path: Path, dataset: SemanticDataset) -> None:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        BlockCollection,
        ExtensionBlock,
        GlobalMetaBlock,
        IndexBlock,
        StringPoolBlock,
        ZpWriter,
    )

    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=3,
            source_type="semantic-test",
            source_file_name="semantic-test",
            source_file_hash="3" * 64,
            run_count=0,
            spectrum_count=0,
            chromatogram_count=0,
            array_count=0,
            created_at=datetime.now(timezone.utc),
            generator_name="pytest",
            generator_version="1",
        ),
        string_pool=StringPoolBlock([]),
        indexes=IndexBlock(scan_index=[], rt_index=[], spectrum_id_index=[]),
        extensions=[
            ExtensionBlock(
                extension_type="viewer_semantic_dataset",
                extension_version=str(dataset.schema_version),
                payload=semantic_extension_payload(dataset),
            )
        ],
    )
    ZpWriter().write(path, blocks, format_version=3)


def test_preflight_accepts_renamed_format_neutral_table(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    plan = DeclarativeImportPlan.model_validate(_payload())

    report = preflight_declarative_plan(source_root=tmp_path, plan=plan)

    assert report.status == "PASSED"
    assert report.mapped_field_count == 4
    assert report.explicitly_unmapped_field_count == 3
    assert report.requested_view_ids == ("bu.matches",)


def test_preflight_rejects_silent_source_field_drop(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    payload = _payload()
    payload["unmapped_fields"] = {"identifications": ["protein", "score"]}
    plan = DeclarativeImportPlan.model_validate(payload)

    with pytest.raises(DeclarativePlanError, match="neither mapped nor explicitly unmapped"):
        preflight_declarative_plan(source_root=tmp_path, plan=plan)


def test_preflight_rejects_silently_ignored_directory_asset(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    (tmp_path / "unknown.bin").write_bytes(b"opaque")
    plan = DeclarativeImportPlan.model_validate(_payload())

    with pytest.raises(DeclarativePlanError, match="no input or explicit disposition"):
        preflight_declarative_plan(source_root=tmp_path, plan=plan)

    payload = _payload()
    payload["asset_dispositions"] = [
        {
            "relative_path": "unknown.bin",
            "disposition": "UNSUPPORTED",
            "reason": "No trusted reader is registered for this binary.",
            "evidence_refs": ["obs:unknown-bin"],
        }
    ]
    accepted = preflight_declarative_plan(
        source_root=tmp_path,
        plan=DeclarativeImportPlan.model_validate(payload),
    )
    assert accepted.status == "PASSED"


def test_preflight_rejects_unproven_retention_time_unit(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    payload = _payload()
    payload["field_mappings"][3]["unit"] = None
    plan = DeclarativeImportPlan.model_validate(payload)

    with pytest.raises(DeclarativePlanError, match="must declare minute") as exc_info:
        preflight_declarative_plan(source_root=tmp_path, plan=plan)
    assert exc_info.value.code == "UNIT_AMBIGUOUS"


def test_preflight_rejects_list_transform_for_scalar_peptide_sequence(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    payload = _payload()
    payload["field_mappings"][2]["transform"] = "semicolon_split"
    plan = DeclarativeImportPlan.model_validate(payload)

    with pytest.raises(DeclarativePlanError, match="incompatible scalar value shape"):
        preflight_declarative_plan(source_root=tmp_path, plan=plan)


def test_preflight_rejects_scalar_accession_mapping_for_observed_list_values(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    text = (tmp_path / "renamed-results.tsv").read_text(encoding="utf-8")
    (tmp_path / "renamed-results.tsv").write_text(
        text.replace("P42", "P42;P43"),
        encoding="utf-8",
    )
    payload = _payload()
    payload["field_mappings"].append(
        {
            "mapping_id": "protein-accession",
            "source_id": "identifications",
            "source_field": "protein",
            "target_entity": "protein",
            "target_field": "accession",
            "value_kind": "string",
            "required": False,
            "transform": "identity",
            "evidence_refs": ["obs:protein"],
        }
    )
    payload["unmapped_fields"] = {"identifications": ["score", "unused"]}

    with pytest.raises(DeclarativePlanError, match="must use semicolon_split") as exc_info:
        preflight_declarative_plan(
            source_root=tmp_path,
            plan=DeclarativeImportPlan.model_validate(payload),
        )

    assert exc_info.value.code == "SCIENTIFIC_SEMANTIC_UNKNOWN"


@pytest.mark.parametrize("relative_path", ["../escape.tsv", "C:/escape.tsv", "/escape.tsv"])
def test_contract_rejects_paths_outside_case(relative_path: str) -> None:
    payload = _payload()
    payload["sources"][0]["relative_path"] = relative_path

    with pytest.raises(ValidationError):
        DeclarativeImportPlan.model_validate(payload)


def test_contract_rejects_unknown_transform() -> None:
    payload = _payload()
    payload["field_mappings"][0]["transform"] = "python_eval"

    with pytest.raises(ValidationError):
        DeclarativeImportPlan.model_validate(payload)


def test_capability_contract_exposes_executor_value_shapes() -> None:
    from app.declarative_ingest import build_declarative_ingest_capabilities

    contracts = build_declarative_ingest_capabilities()["target_contracts"]

    assert contracts["identification.protein_group_ids"] == {
        "output_shape": "list",
        "allowed_value_kinds": ["string"],
        "allowed_transforms": ["semicolon_split", "singleton_list"],
    }
    assert contracts["identification.rt_seconds"]["allowed_transforms"] == [
        "identity",
        "minute_to_second",
    ]
    assert contracts["protein.is_decoy"]["allowed_value_kinds"] == ["boolean"]
    views = build_declarative_ingest_capabilities()["registered_views"]
    assert views["bu.matches"]["analysis_modes"] == ["BOTTOM_UP"]
    assert views["fragment_annotation"]["requirements"][-1] == {
        "entity": "fragment_annotations",
        "required": True,
    }


def test_executor_preserves_source_rows_and_distinguishes_missing_fasta(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    payload = _payload()
    payload["field_mappings"].extend(
        [
            {
                "mapping_id": "protein-accessions",
                "source_id": "identifications",
                "source_field": "protein",
                "target_entity": "identification",
                "target_field": "protein_accessions",
                "value_kind": "string",
                "required": False,
                "transform": "semicolon_split",
                "evidence_refs": ["obs:protein"],
            },
        ]
    )
    payload["unmapped_fields"] = {"identifications": ["score", "unused"]}
    plan = DeclarativeImportPlan.model_validate(payload)

    dataset = execute_plan_to_semantic_dataset(
        source_root=tmp_path,
        source_fingerprint="a" * 32,
        plan=plan,
    )

    assert len(dataset.identifications) == 1
    assert len(dataset.peptides) == 1
    assert len(dataset.proteins) == 1
    assert dataset.proteins[0].accession == "P42"
    assert dataset.proteins[0].sequence is None
    assert dataset.proteins[0].sequence_state == "MISSING"
    assert dataset.identifications[0].source_fields["unused"] == "kept-by-source-fields"
    assert dataset.identifications[0].rt_seconds == 90.0
    assert any(item.startswith("REFERENCE_SEQUENCE_MISSING") for item in dataset.warnings)


def test_repeated_psm_rows_do_not_become_conflicting_protein_source_rows(tmp_path: Path) -> None:
    (tmp_path / "renamed-results.tsv").write_text(
        "record\tsample\tpeptide\trt\tprotein\tscore\tunused\n"
        "p1\trun-a\tPEPTIDE\t1.5\tP42\t42\tfirst\n"
        "p2\trun-a\tPEPTIDER\t2.0\tP42\t41\tsecond\n",
        encoding="utf-8",
    )
    payload = _payload()
    payload["field_mappings"].append(
        {
            "mapping_id": "protein-accession",
            "source_id": "identifications",
            "source_field": "protein",
            "target_entity": "protein",
            "target_field": "accession",
            "value_kind": "string",
            "required": False,
            "transform": "semicolon_split",
            "evidence_refs": ["obs:protein"],
        }
    )
    payload["unmapped_fields"] = {"identifications": ["score", "unused"]}

    dataset = execute_plan_to_semantic_dataset(
        source_root=tmp_path,
        source_fingerprint="e" * 32,
        plan=DeclarativeImportPlan.model_validate(payload),
    )

    assert len(dataset.identifications) == 2
    assert {item.source_fields["unused"] for item in dataset.identifications} == {"first", "second"}
    assert len(dataset.proteins) == 1
    assert dataset.proteins[0].accession == "P42"
    assert dataset.proteins[0].source_fields == {}


def test_executor_uses_supplied_fasta_without_fabricating_unmatched_sequences(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    (tmp_path / "database.fasta").write_text(">P42 exact\nPEPTIDE\n>OTHER\nAAAA\n", encoding="utf-8")
    payload = _payload()
    payload["sources"].append(
        {
            "source_id": "reference",
            "relative_path": "database.fasta",
            "role": "reference_sequences",
            "reader": "fasta",
            "required": False,
            "required_fields": [],
        }
    )
    payload["field_mappings"].append(
        {
            "mapping_id": "protein-accessions",
            "source_id": "identifications",
            "source_field": "protein",
            "target_entity": "identification",
            "target_field": "protein_accessions",
            "value_kind": "string",
            "required": False,
            "transform": "semicolon_split",
            "evidence_refs": ["obs:protein"],
        }
    )
    payload["unmapped_fields"] = {"identifications": ["score", "unused"]}
    plan = DeclarativeImportPlan.model_validate(payload)

    dataset = execute_plan_to_semantic_dataset(
        source_root=tmp_path,
        source_fingerprint="b" * 32,
        plan=plan,
    )

    assert dataset.proteins[0].sequence == "PEPTIDE"
    assert dataset.proteins[0].sequence_state == "DIRECT"


def test_optional_declared_fasta_can_be_absent_without_blocking_entities(tmp_path: Path) -> None:
    _write_table(tmp_path / "renamed-results.tsv")
    payload = _payload()
    payload["sources"].append(
        {
            "source_id": "reference",
            "relative_path": "missing-search.fasta",
            "role": "reference_sequences",
            "reader": "fasta",
            "required": False,
            "required_fields": [],
        }
    )
    payload["field_mappings"].append(
        {
            "mapping_id": "protein-accessions",
            "source_id": "identifications",
            "source_field": "protein",
            "target_entity": "identification",
            "target_field": "protein_accessions",
            "value_kind": "string",
            "required": False,
            "transform": "semicolon_split",
            "evidence_refs": ["obs:protein"],
        }
    )
    payload["unmapped_fields"] = {"identifications": ["score", "unused"]}
    plan = DeclarativeImportPlan.model_validate(payload)

    dataset = execute_plan_to_semantic_dataset(
        source_root=tmp_path,
        source_fingerprint="b" * 32,
        plan=plan,
    )

    assert len(dataset.identifications) == 1
    assert dataset.proteins[0].sequence_state == "MISSING"
    assert any(item.startswith("REFERENCE_SEQUENCE_PARTIAL") for item in dataset.warnings)


def test_table_only_plan_writes_deep_validated_semantic_zp(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_table(source_root / "renamed-results.tsv")
    plan = DeclarativeImportPlan.model_validate(_payload())

    artifact = build_declarative_zp_artifact(
        source_root=source_root,
        source_fingerprint="c" * 32,
        plan=plan,
        output_path=tmp_path / "output" / "candidate.zp",
    )

    assert artifact.path.is_file()
    assert artifact.validation_mode == "deep"
    assert artifact.semantic_verification["entity_counts"]["identifications"] == 1
    assert artifact.semantic_verification["spectrum_link_states"] == {"MISSING": 1}
    assert read_semantic_zp(artifact.path) == artifact.semantic_dataset


@pytest.mark.parametrize(
    ("semantic_run_count", "core_run_count"),
    [(2, 1), (1, 2)],
)
def test_spectrum_link_rejects_unscoped_multi_run_association(
    semantic_run_count: int,
    core_run_count: int,
) -> None:
    with pytest.raises(DeclarativeExecutionError) as exc_info:
        zp_artifact_module._link_identifications_to_spectra(
            _spectrum_link_plan(),
            _semantic_for_spectrum_link(run_count=semantic_run_count),
            _core_blocks(run_count=core_run_count),
        )

    assert exc_info.value.code == "RUN_ASSOCIATION_AMBIGUOUS"


def test_spectrum_link_rejects_conflicting_source_identity() -> None:
    semantic = _semantic_for_spectrum_link(native_id="controllerType=0 controllerNumber=1 scan=999")

    with pytest.raises(DeclarativeExecutionError) as exc_info:
        zp_artifact_module._link_identifications_to_spectra(
            _spectrum_link_plan(),
            semantic,
            _core_blocks(),
        )

    assert exc_info.value.code == "RUN_ASSOCIATION_AMBIGUOUS"


@pytest.mark.parametrize(
    ("source_file", "source_sha256"),
    [("different.mzML", "3" * 64), ("spectra.mzML", "4" * 64)],
)
def test_spectrum_link_rejects_core_run_from_different_mzml_source(
    source_file: str,
    source_sha256: str,
) -> None:
    with pytest.raises(DeclarativeExecutionError) as exc_info:
        zp_artifact_module._link_identifications_to_spectra(
            _spectrum_link_plan(),
            _semantic_for_spectrum_link(),
            _core_blocks(source_file=source_file, source_sha256=source_sha256),
        )

    assert exc_info.value.code == "RUN_ASSOCIATION_AMBIGUOUS"


def test_spectrum_link_binds_single_semantic_run_to_declared_mzml_source() -> None:
    linked = zp_artifact_module._link_identifications_to_spectra(
        _spectrum_link_plan(),
        _semantic_for_spectrum_link(),
        _core_blocks(),
    )

    assert linked.runs[0].source_file == "spectra.mzML"
    assert linked.identifications[0].spectrum_id == "spectrum:1"
    assert linked.identifications[0].source_native_id == "controllerType=0 controllerNumber=1 scan=7"


def test_read_semantic_zp_rejects_array_edge_without_relationship(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_table(source_root / "renamed-results.tsv")
    semantic = execute_plan_to_semantic_dataset(
        source_root=source_root,
        source_fingerprint="4" * 32,
        plan=DeclarativeImportPlan.model_validate(_payload()),
    ).model_copy(update={"relationships": []})
    path = tmp_path / "missing-relationship.zp"
    _write_semantic_only_zp(path, semantic)

    with pytest.raises(DeclarativeExecutionError, match="arrays and relationships are inconsistent"):
        read_semantic_zp(path)


def test_read_semantic_zp_rejects_relationship_edge_not_present_in_arrays(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_table(source_root / "renamed-results.tsv")
    semantic_payload = execute_plan_to_semantic_dataset(
        source_root=source_root,
        source_fingerprint="5" * 32,
        plan=DeclarativeImportPlan.model_validate(_payload()),
    ).model_dump(mode="json")
    semantic_payload["peptides"].append(
        {
            "peptide_id": "peptide:other",
            "sequence": "OTHER",
            "identification_ids": [],
            "protein_ids": [],
            "modified_sequences": [],
            "evidence_refs": [],
        }
    )
    semantic_payload["relationships"][0]["right_id"] = "peptide:other"
    path = tmp_path / "extra-relationship.zp"
    _write_semantic_only_zp(path, SemanticDataset.model_validate(semantic_payload))

    with pytest.raises(DeclarativeExecutionError, match="arrays and relationships are inconsistent"):
        read_semantic_zp(path)


def test_multiple_quantification_channels_preserve_zero_and_missing(tmp_path: Path) -> None:
    (tmp_path / "quant.tsv").write_text(
        "id\trun\tsequence\treporter126\treporter127\n"
        "1\trun-a\tPEPTIDE\t0\t\n",
        encoding="utf-8",
    )
    base_mappings = [
        ("id", "id", "identification", "source_id", "string"),
        ("run", "run", "run", "name", "string"),
        ("sequence", "sequence", "peptide", "sequence", "string"),
    ]
    payload = {
        "schema_version": 1,
        "plan_id": "multiplex-quant-v1",
        "analysis_mode": "BOTTOM_UP",
        "sources": [
            {
                "source_id": "table",
                "relative_path": "quant.tsv",
                "role": "quantified_identifications",
                "reader": "delimited",
                "delimiter": "\t",
                "required": True,
                "required_fields": ["id", "run", "sequence", "reporter126", "reporter127"],
            }
        ],
        "field_mappings": [
            *[
                {
                    "mapping_id": mapping_id,
                    "source_id": "table",
                    "source_field": source_field,
                    "target_entity": entity,
                    "target_field": target,
                    "value_kind": kind,
                    "required": True,
                    "evidence_refs": [f"obs:{source_field}"],
                }
                for mapping_id, source_field, entity, target, kind in base_mappings
            ],
            *[
                {
                    "mapping_id": f"quant-{channel}",
                    "source_id": "table",
                    "source_field": field,
                    "target_entity": "quantification",
                    "target_field": "value",
                    "value_kind": "float",
                    "required": False,
                    "unit": "reporter_intensity",
                    "measurement_name": channel,
                    "evidence_refs": [f"obs:{field}"],
                }
                for field, channel in (("reporter126", "126"), ("reporter127", "127"))
            ],
        ],
        "unmapped_fields": {"table": []},
        "requested_views": [{"view_id": "quantification"}],
    }
    plan = DeclarativeImportPlan.model_validate(payload)

    dataset = execute_plan_to_semantic_dataset(
        source_root=tmp_path,
        source_fingerprint="f" * 32,
        plan=plan,
    )

    by_channel = {item.channel: item.value for item in dataset.quantification}
    assert by_channel == {"126": 0.0, "127": None}


def test_jsonl_late_schema_drift_is_not_silently_ignored(tmp_path: Path) -> None:
    rows = [
        {"id": str(index), "run": "run-a", "sequence": "PEPTIDE"}
        for index in range(100)
    ]
    rows.append({"id": "late", "run": "run-a", "sequence": "PEPTIDE", "late_field": "surprise"})
    (tmp_path / "records.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows) + "\n",
        encoding="utf-8",
    )
    plan = DeclarativeImportPlan.model_validate(
        {
            "schema_version": 1,
            "plan_id": "jsonl-drift-v1",
            "analysis_mode": "BOTTOM_UP",
            "sources": [
                {
                    "source_id": "rows",
                    "relative_path": "records.jsonl",
                    "role": "identifications",
                    "reader": "jsonl",
                    "required": True,
                    "required_fields": ["id", "run", "sequence"],
                }
            ],
            "field_mappings": [
                {
                    "mapping_id": mapping_id,
                    "source_id": "rows",
                    "source_field": source_field,
                    "target_entity": entity,
                    "target_field": target,
                    "value_kind": "string",
                    "required": True,
                    "evidence_refs": [f"obs:{source_field}"],
                }
                for mapping_id, source_field, entity, target in (
                    ("id", "id", "identification", "source_id"),
                    ("run", "run", "run", "name"),
                    ("sequence", "sequence", "peptide", "sequence"),
                )
            ],
            "unmapped_fields": {"rows": []},
        }
    )

    with pytest.raises(ValueError, match="neither mapped nor explicitly unmapped: late_field") as exc_info:
        execute_plan_to_semantic_dataset(
            source_root=tmp_path,
            source_fingerprint="a" * 32,
            plan=plan,
        )
    assert getattr(exc_info.value, "code") == "DECLARATIVE_PLAN_INVALID"
