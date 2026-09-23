from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_import import binary_executor
from app.agent_import.binary_executor import execute_binary_plan
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentBinaryPlanError


def test_binary_executor_resolves_case_relative_input_and_returns_zp_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    existing = source / "candidate.zp"
    existing.write_bytes(b"source-zp")
    certificate = tmp_path / "validation.json"
    certificate.write_text("{}", encoding="utf-8")
    prepared_path = tmp_path / "prepared.zp"
    prepared_path.write_bytes(b"prepared-zp")
    calls: list[dict[str, object]] = []

    def prepare(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            path=prepared_path,
            format_version=3,
            output_sha256="a" * 64,
            validation_mode="deep",
            certificate_path=certificate,
        )

    plan = AgentCandidatePlan.model_validate(
        {
            "schema_version": 1,
            "analysis_category": "SPECTRA_ONLY",
            "source_profile": "existing-zp-package",
            "binary_operation": "register_existing_zp",
            "zp_conversion_plan": {
                "relative_source": "candidate.zp",
                "target_format_version": 3,
            },
        }
    )

    result = execute_binary_plan(
        case_id="case-123",
        source_root=source,
        source_fingerprint="b" * 32,
        plan=plan,
        prepare=prepare,
    )

    assert calls == [
        {
            "source_path": existing.resolve(),
            "binary_operation": "register_existing_zp",
            "case_id": "case-123",
            "format_version": 3,
        }
    ]
    assert result.zp_path == prepared_path
    assert result.output_sha256 == "a" * 64
    assert result.source_fingerprint == "b" * 32
    assert result.validation_mode == "deep"


def test_binary_executor_consumes_format_neutral_declarative_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "unknown.tsv").write_text(
        "id\trun\tsequence\tunused\n1\trun-a\tPEPTIDE\tpreserved\n",
        encoding="utf-8",
    )
    output_root = tmp_path / "zp-output"
    monkeypatch.setattr(binary_executor.settings, "zp_output_root", output_root)
    plan = AgentCandidatePlan.model_validate(
        {
            "schema_version": 3,
            "analysis_category": "BOTTOM_UP",
            "source_profile": "agent-discovered-table",
            "binary_operation": "convert_declared_mapping_to_zp",
            "zp_conversion_plan": {
                "relative_source": "unknown.tsv",
                "target_format_version": 3,
                "declarative_plan": {
                    "schema_version": 1,
                    "plan_id": "unknown-bottom-up-v1",
                    "analysis_mode": "BOTTOM_UP",
                    "sources": [
                        {
                            "source_id": "ids",
                            "relative_path": "unknown.tsv",
                            "role": "identifications",
                            "reader": "delimited",
                            "delimiter": "\t",
                            "required": True,
                            "required_fields": ["id", "run", "sequence"],
                        }
                    ],
                    "field_mappings": [
                        {
                            "mapping_id": "id",
                            "source_id": "ids",
                            "source_field": "id",
                            "target_entity": "identification",
                            "target_field": "source_id",
                            "value_kind": "string",
                            "required": True,
                            "evidence_refs": ["obs:id"],
                        },
                        {
                            "mapping_id": "run",
                            "source_id": "ids",
                            "source_field": "run",
                            "target_entity": "run",
                            "target_field": "name",
                            "value_kind": "string",
                            "required": True,
                            "evidence_refs": ["obs:run"],
                        },
                        {
                            "mapping_id": "sequence",
                            "source_id": "ids",
                            "source_field": "sequence",
                            "target_entity": "peptide",
                            "target_field": "sequence",
                            "value_kind": "string",
                            "required": True,
                            "evidence_refs": ["obs:sequence"],
                        },
                    ],
                    "unmapped_fields": {"ids": ["unused"]},
                    "requested_views": [
                        {"view_id": "bu.matches"},
                        {"view_id": "bu.peptides"},
                    ],
                },
            },
        }
    )

    with pytest.raises(AgentBinaryPlanError, match="persisted Agent 1 observations"):
        execute_binary_plan(
            case_id="case-without-evidence",
            source_root=source,
            source_fingerprint="d" * 32,
            plan=plan,
        )

    result = execute_binary_plan(
        case_id="case-declarative",
        source_root=source,
        source_fingerprint="d" * 32,
        plan=plan,
        trusted_observations={
            key: {
                "relative_path": "unknown.tsv",
                "facts": {"columns": [{"name": name}]},
            }
            for key, name in (
                ("obs:id", "id"),
                ("obs:run", "run"),
                ("obs:sequence", "sequence"),
            )
        },
    )

    assert result.zp_path.is_file()
    assert result.semantic_verification["plan_id"] == "unknown-bottom-up-v1"
    assert result.semantic_verification["entity_counts"]["identifications"] == 1
    assert result.semantic_verification["warnings"]

    resumed = execute_binary_plan(
        case_id="case-declarative",
        source_root=source,
        source_fingerprint="d" * 32,
        plan=plan,
        trusted_observations={
            key: {
                "relative_path": "unknown.tsv",
                "facts": {"columns": [{"name": name}]},
            }
            for key, name in (
                ("obs:id", "id"),
                ("obs:run", "run"),
                ("obs:sequence", "sequence"),
            )
        },
    )
    assert resumed.zp_path == result.zp_path
    assert resumed.output_sha256 == result.output_sha256
