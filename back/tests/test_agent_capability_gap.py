from sqlalchemy import create_engine

from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.migrations import ensure_agent_import_schema


def test_missing_implementation_is_not_presented_as_scientific_user_question(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    case = service.create_case(source_ref=str(tmp_path), dataset_fingerprint="a" * 32,
                               analysis_category="BOTTOM_UP", source_profile="table", format_details=None)
    service.start_analysis(case.case_id)
    service.save_strategy(case.case_id, {"blueprint": {}})
    failed = service.record_candidate_needs_user(case.case_id, AgentCandidatePlan(
        status="UNSUPPORTED", analysis_category="BOTTOM_UP", source_profile="table",
        questions=["Protein-group-level quantitative projection is not implemented by this schema."],
    ))
    assert failed.status.value == "FAILED"
    assert failed.verification_payload["failure_class"] == "ENGINEERING_REVIEW"
    artifacts = service.list_artifacts(case.case_id)
    gap = next(item for item in artifacts if item.artifact_type == "capability_gap")
    assert gap.structured_payload["engineering_status"] == "BLOCKED_ENGINEERING_GATE"
    assert failed.autonomous_attempt_used == 0
