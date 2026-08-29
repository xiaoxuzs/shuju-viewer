from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine

from app.agent_import.binary_executor import BinaryExecutionResult
from app.agent_import.api import _case_out
from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.states import CaseStatus


def _service(tmp_path: Path) -> CaseService:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'agent.sqlite').as_posix()}", future=True)
    ensure_agent_import_schema(engine)
    return CaseService(engine)


def _case(service: CaseService) -> str:
    return service.create_case(
        source_ref="E:/data/unknown",
        dataset_fingerprint="a" * 32,
        analysis_category="SPECTRA_ONLY",
        source_profile="unknown-zp",
        format_details="fixture",
    ).case_id


def _plan() -> AgentCandidatePlan:
    return AgentCandidatePlan.model_validate(
        {
            "schema_version": 1,
            "analysis_category": "SPECTRA_ONLY",
            "source_profile": "unknown-zp",
            "binary_operation": "register_existing_zp",
            "zp_conversion_plan": {"relative_source": "candidate.zp", "target_format_version": 3},
        }
    )


def test_case_records_zp_evidence_before_review(tmp_path: Path) -> None:
    service = _service(tmp_path)
    case_id = _case(service)
    zp = tmp_path / "candidate.zp"
    zp.write_bytes(b"candidate")
    certificate = tmp_path / "deep.json"
    certificate.write_text("{}", encoding="utf-8")

    service.start_analysis(case_id)
    service.save_strategy(case_id, {"decision": "READY"})
    service.save_candidate(case_id, _plan())
    service.start_verification(case_id)
    ready = service.record_ready(
        case_id,
        BinaryExecutionResult(
            zp_path=zp,
            output_sha256="b" * 64,
            format_version=3,
            validation_mode="deep",
            validation_certificate_path=certificate,
            source_fingerprint="a" * 32,
        ),
    )

    assert ready.status == CaseStatus.READY_FOR_REVIEW
    assert ready.candidate_zp_path == str(zp)
    public_evidence = json.dumps(ready.verification_payload)
    assert str(zp) not in public_evidence
    assert str(certificate) not in public_evidence
    assert all(str(zp) not in json.dumps(item.structured_payload) for item in service.list_messages(case_id))
    api_payload = _case_out(ready).model_dump_json()
    assert "E:/data/unknown" not in api_payload
    assert str(zp) not in api_payload
    assert str(certificate) not in api_payload
    assert [item.artifact_type for item in service.list_artifacts(case_id)] == [
        "strategy",
        "candidate_plan",
        "candidate_zp",
        "deep_validation_certificate",
        "verification_summary",
    ]
    assert service.list_attempts(case_id)[0].result == "PASSED"


def test_three_binary_failures_require_user_and_answer_starts_guided_revision(tmp_path: Path) -> None:
    service = _service(tmp_path)
    case_id = _case(service)

    for attempt in range(3):
        current = service.get_case(case_id)
        if current.status == CaseStatus.CREATED:
            service.start_analysis(case_id)
        service.record_failure(case_id, code="ZP_UNSUPPORTED_SOURCE", summary=f"failure {attempt + 1}")

    waiting = service.get_case(case_id)
    assert waiting.status == CaseStatus.NEEDS_USER
    assert waiting.autonomous_attempt_used == 3
    assert len(service.list_notifications()) == 1

    resumed = service.submit_user_answer(
        case_id,
        content="The binary is exported by Vendor X version 2.",
        expected_version=waiting.version,
        idempotency_key="answer-1",
    )
    assert resumed.status == CaseStatus.ANALYZING
    assert resumed.context_revision == 2
    assert resumed.guided_attempt_no == 1
    assert service.list_notifications() == []
