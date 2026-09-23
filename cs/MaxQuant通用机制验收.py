"""用 MaxQuant 样本验收通用声明式执行器；生产代码不含 MaxQuant 分支。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACK_ROOT = REPO_ROOT / "back"
if str(BACK_ROOT) not in sys.path:
    sys.path.insert(0, str(BACK_ROOT))

from app.dataset_capabilities import compile_semantic_capability_report, get_view_catalog  # noqa: E402
from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact  # noqa: E402
from app.fingerprint import compute_dataset_metadata_fingerprint  # noqa: E402


def _header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream, delimiter="\t"))
    return header


def _mapping(
    mapping_id: str,
    source_id: str,
    source_field: str,
    target_entity: str,
    target_field: str,
    value_kind: str,
    *,
    transform: str = "identity",
    unit: str | None = None,
    required: bool = False,
) -> dict[str, object]:
    return {
        "mapping_id": mapping_id,
        "source_id": source_id,
        "source_field": source_field,
        "target_entity": target_entity,
        "target_field": target_field,
        "value_kind": value_kind,
        "required": required,
        "transform": transform,
        "unit": unit,
        "evidence_refs": [f"maxquant-acceptance:{source_id}:{source_field}"],
    }


def build_plan(
    source: Path,
    *,
    include_spectra: bool = True,
    include_fasta: bool = True,
) -> DeclarativeImportPlan:
    evidence_fields = _header(source / "evidence.txt")
    group_fields = _header(source / "proteinGroups.txt")
    evidence_mappings = [
        _mapping("psm-id", "evidence", "id", "identification", "source_id", "string", required=True),
        _mapping("run-name", "evidence", "Raw file", "run", "name", "string", required=True),
        _mapping("peptide", "evidence", "Sequence", "peptide", "sequence", "string", required=True),
        _mapping("modified", "evidence", "Modified sequence", "identification", "modified_sequence", "string"),
        _mapping("charge", "evidence", "Charge", "identification", "charge", "integer"),
        _mapping("mz", "evidence", "m/z", "identification", "precursor_mz", "float", unit="Th"),
        _mapping("mass", "evidence", "Mass", "identification", "neutral_mass", "float", unit="Da"),
        _mapping(
            "rt",
            "evidence",
            "Retention time",
            "identification",
            "rt_seconds",
            "float",
            transform="minute_to_second",
            unit="minute",
        ),
        _mapping("scan", "evidence", "MS/MS scan number", "identification", "scan_number", "integer"),
        _mapping(
            "proteins",
            "evidence",
            "Proteins",
            "identification",
            "protein_accessions",
            "string",
            transform="semicolon_split",
        ),
        _mapping(
            "groups",
            "evidence",
            "Protein group IDs",
            "identification",
            "protein_group_ids",
            "string",
            transform="semicolon_split",
        ),
        _mapping("score", "evidence", "Score", "identification", "score", "float"),
        _mapping("pep", "evidence", "PEP", "identification", "pep", "float"),
        _mapping(
            "intensity",
            "evidence",
            "Intensity",
            "quantification",
            "value",
            "float",
            unit="source_intensity",
        ),
        _mapping("modification", "evidence", "Modifications", "modification", "name", "string"),
        _mapping("experiment", "evidence", "Experiment", "quantification", "sample", "string"),
    ]
    group_mappings = [
        _mapping("group-id", "protein-groups", "id", "protein_group", "source_id", "string", required=True),
        _mapping(
            "group-members",
            "protein-groups",
            "Protein IDs",
            "protein_group",
            "member_accessions",
            "string",
            transform="semicolon_split",
        ),
        _mapping(
            "group-leading",
            "protein-groups",
            "Majority protein IDs",
            "protein_group",
            "leading_accession",
            "string",
            transform="first_semicolon_value",
        ),
        _mapping("group-q", "protein-groups", "Q-value", "protein_group", "q_value", "float"),
    ]
    mapped_evidence = {str(item["source_field"]) for item in evidence_mappings}
    mapped_groups = {str(item["source_field"]) for item in group_mappings}
    sources: list[dict[str, object]] = [
        {
            "source_id": "evidence",
            "relative_path": "evidence.txt",
            "role": "identifications",
            "reader": "delimited",
            "delimiter": "\t",
            "required": True,
            "required_fields": sorted(mapped_evidence),
        },
        {
            "source_id": "protein-groups",
            "relative_path": "proteinGroups.txt",
            "role": "protein_groups",
            "reader": "delimited",
            "delimiter": "\t",
            "required": True,
            "required_fields": sorted(mapped_groups),
        },
    ]
    if include_spectra:
        sources.append(
            {
                "source_id": "spectra",
                "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
                "role": "spectrum_source",
                "reader": "mzml",
                "required": False,
                "required_fields": [],
            }
        )
    if include_fasta:
        sources.append(
            {
                "source_id": "fasta",
                "relative_path": "inputs/erwinia.fasta",
                "role": "reference_sequences",
                "reader": "fasta",
                "required": False,
                "required_fields": [],
                "fasta_accession_rule": "uniprot_pipe_accession",
                "accession_rule_evidence_refs": ["maxquant-acceptance:fasta-uniprot-headers"],
            }
        )
    declared_paths = {str(item["relative_path"]) for item in sources}
    asset_dispositions = [
        {
            "relative_path": path.relative_to(source).as_posix(),
            "disposition": "PROVENANCE_ONLY",
            "reason": "Retained at the source root and recorded by the dataset fingerprint; not required by this mapping.",
            "evidence_refs": [f"maxquant-acceptance:inventory:{path.relative_to(source).as_posix()}"],
        }
        for path in sorted(source.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.relative_to(source).as_posix() not in declared_paths
    ]
    joins = (
        [
            {
                "join_id": "psm-to-ms2",
                "relationship": "identification_to_spectrum",
                "left_source_id": "evidence",
                "left_field": "MS/MS scan number",
                "right_source_id": "spectra",
                "right_field": "scan_number",
                "cardinality": "many_to_one",
                "transform": "identity",
                "required": True,
                "on_failure": "BLOCK_DATASET",
                "evidence_refs": ["maxquant-acceptance:all-scans-checked"],
            }
        ]
        if include_spectra
        else []
    )
    return DeclarativeImportPlan.model_validate(
        {
            "schema_version": 1,
            "plan_id": "maxquant-acceptance-through-generic-engine-v1",
            "analysis_mode": "BOTTOM_UP",
            "acquisition_mode": "dda" if include_spectra else None,
            "acquisition_mode_evidence_refs": (
                ["maxquant-acceptance:dda-acquisition"] if include_spectra else []
            ),
            "sources": sources,
            "field_mappings": [*evidence_mappings, *group_mappings],
            "join_rules": joins,
            "unmapped_fields": {
                "evidence": [item for item in evidence_fields if item not in mapped_evidence],
                "protein-groups": [item for item in group_fields if item not in mapped_groups],
            },
            "requested_views": [
                {"view_id": item.view_id}
                for item in get_view_catalog("BOTTOM_UP")
            ],
            "asset_dispositions": asset_dispositions,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=os.getenv("VIEWER_MAXQUANT_DATASET_ROOT"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-report", action="store_true")
    parser.add_argument("--omit-spectra", action="store_true")
    parser.add_argument("--omit-fasta", action="store_true")
    args = parser.parse_args()
    if args.source is None:
        raise SystemExit("请通过 --source 或 VIEWER_MAXQUANT_DATASET_ROOT 指定样本目录")
    source = args.source.resolve(strict=True)
    plan = build_plan(
        source,
        include_spectra=not args.omit_spectra,
        include_fasta=not args.omit_fasta,
    )
    fingerprint = compute_dataset_metadata_fingerprint(source)
    artifact = build_declarative_zp_artifact(
        source_root=source,
        source_fingerprint=fingerprint.fingerprint,
        plan=plan,
        output_path=args.output,
    )
    report = compile_semantic_capability_report(
        dataset_id=1,
        source_case_id="maxquant-generic-acceptance",
        semantic=artifact.semantic_dataset,
    )
    counts = artifact.semantic_verification["entity_counts"]
    assert counts["identifications"] == 35
    assert counts["peptides"] == 32
    assert counts["proteins"] == 33
    assert counts["protein_groups"] == 32
    assert counts["modifications"] == 1
    assert counts["quantification"] == 35
    expected_link_state = {"MISSING": 35} if args.omit_spectra else {"DIRECT": 35}
    assert artifact.semantic_verification["spectrum_link_states"] == expected_link_state
    assert any(item.input_id == "fasta" for item in report.missing_inputs)
    if args.omit_spectra:
        assert any(item.input_id == "spectrum_source" for item in report.missing_inputs)
    summary = {
        "output": str(artifact.path),
        "sha256": artifact.output_sha256,
        "validation_mode": artifact.validation_mode,
        "counts": counts,
        "core_spectrum_count": artifact.semantic_dataset.core_spectrum_count,
        "core_chromatogram_count": artifact.semantic_dataset.core_chromatogram_count,
        "spectrum_link_states": artifact.semantic_verification["spectrum_link_states"],
        "views": {item.view_id: item.availability for item in report.views},
        "missing_inputs": [item.model_dump(mode="json") for item in report.missing_inputs],
    }
    if args.full_report:
        summary["capability_report"] = report.model_dump(mode="json")
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
