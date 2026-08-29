from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.agent_import.binary_executor import execute_binary_plan
from app.agent_import.contracts import AgentCandidatePlan


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
