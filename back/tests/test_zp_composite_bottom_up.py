from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentBinaryPlanError
from app.agent_import.mapping_preflight import preflight_mapping_plan
from app.agent_import.zp_capabilities import build_zp_capabilities
from app.zp_runtime.package import ensure_binary_layer_importable

ensure_binary_layer_importable()

from binary_layer.bottom_up_validator import BottomUpExtensionValidator  # type: ignore[import-not-found]  # noqa: E402
from binary_layer.composite_bottom_up_adapter import (  # type: ignore[import-not-found]  # noqa: E402
    CompositeBottomUpAdapter,
    ExactSpectrumReference,
)
from binary_layer.composite_bottom_up_bundle import (  # type: ignore[import-not-found]  # noqa: E402
    CompositeBottomUpBundleInspector,
)


def test_composite_adapter_preserves_null_and_zero_without_fabricated_modifications(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    hashes = {
        bundle.relative_label(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.identity_files
    }
    report = CompositeBottomUpAdapter().read(
        bundle,
        run_id="run-1",
        spectrum_by_scan={
            11: ExactSpectrumReference("spectrum-11", "scan=11", 60.0)
        },
        source_file_hashes=hashes,
        raw_source_sha1=hashlib.sha1(bundle.raw_source.read_bytes()).hexdigest(),
    )

    document = report.document
    assert (
        len(document.identifications),
        len(document.peptides),
        len(document.proteins),
        len(document.protein_groups),
        len(document.modifications),
        len(document.quantification),
    ) == (1, 1, 1, 1, 0, 2)
    by_kind = {item.entity_kind: item for item in document.quantification}
    assert by_kind["identification"].measurements == {"intensity": None}
    assert by_kind["protein_group"].measurements == {"intensity": 0.0}
    assert document.metadata["modification_vocabulary"] == {
        "fixed": ["Carbamidomethyl (C)"],
        "variable": ["Oxidation (M)", "Acetyl (Protein N-term)"],
        "observed_instances": [],
        "policy": "search-space terms are metadata; only observed localized instances become modification records",
    }


def test_mapping_preflight_accepts_only_canonical_physical_contract(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    plan = _canonical_plan(tmp_path)
    result = preflight_mapping_plan(source_root=tmp_path, plan=plan)
    assert result["status"] == "PASSED"
    assert result["mapping_adapter"] == "maxquant_mzml_v1"

    payload = plan.model_dump(mode="json")
    payload["zp_conversion_plan"]["mapping_plan"]["source_files"][0]["required"] = False
    weakened = AgentCandidatePlan.model_validate(payload)
    with pytest.raises(AgentBinaryPlanError, match="must be declared required"):
        preflight_mapping_plan(source_root=tmp_path, plan=weakened)

    payload = plan.model_dump(mode="json")
    payload["zp_conversion_plan"]["mapping_plan"]["field_mappings"].append(
        {
            "source_file": "evidence.txt",
            "source_field": "Sequence",
            "target_entity": "run",
            "target_field": "run_id",
            "value_kind": "boolean",
            "unit": "nonsense",
            "transform": "identity",
            "required": False,
            "evidence": "malicious extra declaration",
        }
    )
    extra_mapping = AgentCandidatePlan.model_validate(payload)
    with pytest.raises(AgentBinaryPlanError, match="exactly match"):
        preflight_mapping_plan(source_root=tmp_path, plan=extra_mapping)

    payload = plan.model_dump(mode="json")
    payload["zp_conversion_plan"]["mapping_plan"]["field_mappings"][0]["value_kind"] = "boolean"
    wrong_type = AgentCandidatePlan.model_validate(payload)
    with pytest.raises(AgentBinaryPlanError, match="exactly match"):
        preflight_mapping_plan(source_root=tmp_path, plan=wrong_type)


def test_mapping_preflight_rejects_missing_candidate_paths_as_plan_errors(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    plan = _canonical_plan(tmp_path)

    payload = plan.model_dump(mode="json")
    payload["zp_conversion_plan"]["relative_source"] = "missing-source"
    missing_source = AgentCandidatePlan.model_validate(payload)
    with pytest.raises(AgentBinaryPlanError, match="relative_source does not exist"):
        preflight_mapping_plan(source_root=tmp_path, plan=missing_source)

    payload = plan.model_dump(mode="json")
    mapping_plan = payload["zp_conversion_plan"]["mapping_plan"]
    old_path = mapping_plan["source_files"][0]["relative_path"]
    missing_path = "missing-file.raw"
    mapping_plan["source_files"][0]["relative_path"] = missing_path
    for field_mapping in mapping_plan["field_mappings"]:
        if field_mapping["source_file"] == old_path:
            field_mapping["source_file"] = missing_path
    for join_rule in mapping_plan["join_rules"]:
        if join_rule["left_file"] == old_path:
            join_rule["left_file"] = missing_path
        if join_rule["right_file"] == old_path:
            join_rule["right_file"] = missing_path
    for evidence in mapping_plan["evidence"]:
        if evidence["source_file"] == old_path:
            evidence["source_file"] = missing_path
    missing_file = AgentCandidatePlan.model_validate(payload)
    with pytest.raises(AgentBinaryPlanError, match="mapping source file does not exist"):
        preflight_mapping_plan(source_root=tmp_path, plan=missing_file)


def test_bottom_up_validator_rejects_unknown_adapter_identity() -> None:
    issues: list[tuple[str, str]] = []
    BottomUpExtensionValidator._validate_metadata(
        {
            "source_type": "attacker_bundle",
            "adapter_flavor": "fake_adapter",
            "identification_kind": "dda_psm_identification",
            "analysis_mode": "bottom_up_dda",
            "field_coverage": {"unexplained_column_count": 0},
            "source_files": [
                {"source_file": "source.txt", "size": 1, "sha256": "a" * 64}
            ],
        },
        lambda code, message: issues.append((code, message)),
    )
    assert (
        "BOTTOM_UP_INVALID_SCHEMA",
        "metadata Bottom-Up adapter identity is unsupported",
    ) in issues


def _write_bundle(root: Path):
    inputs = root / "inputs"
    derived = root / ".viewer-derived" / "raw-converted-mzml" / "inputs"
    inputs.mkdir(parents=True)
    derived.mkdir(parents=True)
    raw = inputs / "run.raw"
    raw.write_bytes(b"controlled-raw")
    raw_sha1 = hashlib.sha1(raw.read_bytes()).hexdigest()
    (derived / "run.mzML").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML version="1.1.0">
<fileDescription><sourceFileList count="1"><sourceFile id="RAW1" name="run" location="file:///bundle/inputs/run.raw">
<cvParam accession="MS:1000569" name="SHA-1" value="%s"/></sourceFile></sourceFileList></fileDescription>
<run id="run"><spectrumList count="1"><spectrum id="scan=11" index="0" defaultArrayLength="1">
<cvParam accession="MS:1000511" name="ms level" value="2"/></spectrum></spectrumList></run>
</mzML></indexedmzML>""" % raw_sha1,
        encoding="utf-8",
    )
    (inputs / "db.fasta").write_text(">ECA1 Protein one\nPEPTIDE\n", encoding="utf-8")
    (root / "mqpar.xml").write_text(
        """<MaxQuantParams><fastaFiles><FastaFileInfo><fastaFilePath>/redacted/db.fasta</fastaFilePath></FastaFileInfo></fastaFiles>
<maxQuantVersion>2.8.1.0</maxQuantVersion><fixedModifications><string>Carbamidomethyl (C)</string></fixedModifications>
<variableModifications><string>Oxidation (M)</string><string>Acetyl (Protein N-term)</string></variableModifications>
<enzymes><string>Trypsin/P</string></enzymes></MaxQuantParams>""",
        encoding="utf-8",
    )
    _write_tsv(
        root / "evidence.txt",
        [
            "Raw file", "Experiment", "Sequence", "Modifications", "Modified sequence",
            "Charge", "m/z", "Mass", "Retention time", "MS/MS scan number", "Proteins",
            "id", "Protein group IDs", "Score", "PEP", "Intensity",
        ],
        [["run", "run", "PEPTIDE", "Unmodified", "_PEPTIDE_", "2", "500.2", "998.4", "1", "11", "ECA1", "0", "0", "100", "0.001", ""]],
    )
    _write_tsv(
        root / "proteinGroups.txt",
        [
            "Protein IDs", "Majority protein IDs", "Q-value", "Score", "Intensity",
            "Peptide sequences", "Potential contaminant", "id", "Evidence IDs",
        ],
        [["ECA1", "ECA1", "0", "100", "0", "PEPTIDE", "", "0", "0"]],
    )
    return CompositeBottomUpBundleInspector().inspect_bundle(root)


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _canonical_plan(root: Path) -> AgentCandidatePlan:
    del root
    capability = build_zp_capabilities()["mapping_adapters"]["maxquant_mzml_v1"]
    paths = {
        "evidence": "evidence.txt",
        "protein_groups": "proteinGroups.txt",
        "parameters": "mqpar.xml",
        "spectrum_source": ".viewer-derived/raw-converted-mzml/inputs/run.mzML",
        "vendor_raw": "inputs/run.raw",
        "fasta": "inputs/db.fasta",
    }
    sources = []
    for role, contract in capability["required_roles"].items():
        sources.append(
            {
                "relative_path": paths[role],
                "role": role,
                "source_format": contract["source_format"],
                "required": True,
                "required_columns": contract["required_columns"],
            }
        )
    mappings = []
    for (
        role,
        source_field,
        target_entity,
        target_field,
        value_kind,
        unit,
        transform,
    ) in capability["required_field_mappings"]:
        mappings.append(
            {
                "source_file": paths[role],
                "source_field": source_field,
                "target_entity": target_entity,
                "target_field": target_field,
                "value_kind": value_kind,
                "unit": unit,
                "required": True,
                "transform": transform,
                "evidence": "synthetic controlled fixture",
            }
        )
    joins = [
        {
            "left_file": paths[left_role],
            "left_field": left_field,
            "right_file": paths[right_role],
            "right_field": right_field,
            "cardinality": cardinality,
            "transform": transform,
        }
        for left_role, left_field, right_role, right_field, cardinality, transform
        in capability["required_join_rules"]
    ]
    return AgentCandidatePlan.model_validate(
        {
            "schema_version": 2,
            "status": "READY",
            "analysis_category": "BOTTOM_UP",
            "source_profile": "synthetic MaxQuant mzML bundle",
            "binary_operation": "convert_declared_mapping_to_zp",
            "zp_conversion_plan": {
                "relative_source": ".",
                "target_format_version": 3,
                "mapping_plan": {
                    "adapter_id": "maxquant_mzml_v1",
                    "source_format": "maxquant_mzml_bundle",
                    "target_format_version": 3,
                    "source_files": sources,
                    "field_mappings": mappings,
                    "join_rules": joins,
                    "row_policy": "preserve_all_rows",
                    "unmapped_fields": {},
                    "expected_counts": {
                        "spectra": 1,
                        "precursors": 1,
                        "evidence_rows": 1,
                        "protein_groups": 1,
                    },
                    "evidence": [
                        {
                            "source_file": "evidence.txt",
                            "source_field": "MS/MS scan number",
                            "fact": "synthetic exact scan relation",
                        }
                    ],
                },
            },
            "questions": [],
        }
    )
