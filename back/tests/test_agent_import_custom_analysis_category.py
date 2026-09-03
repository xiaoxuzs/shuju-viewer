from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from app.agent_import.api import _analysis_category
from app.agent_import.case_service import CaseService
from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.states import CaseStatus
from app.agent_import.workflow import AgentImportWorkflow


class _CaptureCustomCategoryProvider:
    def __init__(self) -> None:
        self.agent_one_category: str | None = None
        self.agent_two_category: str | None = None

    def analyze_source(self, context):
        self.agent_one_category = context.analysis_category
        return {"analysis_category": context.analysis_category}

    def build_candidate(self, context, _strategy):
        self.agent_two_category = context.analysis_category
        return AgentCandidatePlan(
            schema_version=2,
            status="NEEDS_USER",
            analysis_category=context.analysis_category,
            source_profile=context.requested_source_profile,
            questions=["A custom analysis category requires a controlled physical ZP plan."],
        )


def test_custom_analysis_category_is_preserved_through_case_and_agent_contracts(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'custom-analysis.sqlite').as_posix()}",
        future=True,
    )
    ensure_agent_import_schema(engine)
    service = CaseService(engine)
    source = tmp_path / "custom-source"
    source.mkdir()
    (source / "data.txt").write_text("value\n", encoding="utf-8")
    custom_category = _analysis_category("  DIA-CLIP quantitative imaging  ")
    case = service.create_case(
        source_ref=str(source),
        dataset_fingerprint="d" * 32,
        analysis_category=custom_category,
        source_profile="custom-profile",
        format_details=None,
    )
    provider = _CaptureCustomCategoryProvider()

    waiting = AgentImportWorkflow(service=service, provider=provider).run_case(case.case_id)

    assert service.get_case(case.case_id).analysis_category == "DIA-CLIP quantitative imaging"
    assert provider.agent_one_category == "DIA-CLIP quantitative imaging"
    assert provider.agent_two_category == "DIA-CLIP quantitative imaging"
    assert waiting.status == CaseStatus.NEEDS_USER
    assert waiting.candidate_payload is not None
    assert waiting.candidate_payload["analysis_category"] == "DIA-CLIP quantitative imaging"
