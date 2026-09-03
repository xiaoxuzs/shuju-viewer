#!/usr/bin/env python3
"""Run the real Agent 1 review against a preflight-passed Agent 2 plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "back"
sys.path.insert(0, str(BACKEND_ROOT))

from app.agent_import.contracts import AgentCandidatePlan  # noqa: E402
from app.agent_import.mapping_preflight import preflight_mapping_plan  # noqa: E402
from app.agent_import.model_provider import AgentModelContext, ConfiguredAgentModelProvider  # noqa: E402
from app.agent_import.research_contracts import AgentResearchResult  # noqa: E402
from app.agent_import.source_sampling import summarize_source_root  # noqa: E402
from app.core.config import settings  # noqa: E402


DEFAULT_SOURCE = (
    REPO_ROOT.parent
    / "viewer-agent"
    / "maxquant"
    / "maxquant-viz-data"
    / "single-sample"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = args.source.expanduser().resolve(strict=True)
    research = AgentResearchResult.model_validate_json(
        args.blueprint.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    )
    plan = AgentCandidatePlan.model_validate_json(
        args.plan.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    )
    preflight = preflight_mapping_plan(source_root=source, plan=plan)
    context = AgentModelContext(
        case_id="live-agent1-review-single-sample",
        context_revision=1,
        source_root=str(source),
        analysis_category=research.blueprint.analysis_category,
        requested_source_profile=research.blueprint.source_profile,
        format_details="Review the preflight-passed Agent 2 plan against your approved DatasetBlueprint.",
        dataset_fingerprint="0" * 32,
        source_summary=summarize_source_root(source),
        user_messages=[],
    )
    strategy = {
        "schema_version": 3,
        "decision": "BLUEPRINT_READY",
        "analysis_category": research.blueprint.analysis_category,
        "proposed_source_profile": research.blueprint.source_profile,
        **research.model_dump(mode="json"),
    }
    review = ConfiguredAgentModelProvider().review_candidate(
        context,
        strategy,
        plan,
        preflight,
    )
    payload = review.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        target = args.output.expanduser().resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "model": settings.agent_read_model,
                "status": review.status,
                "issues": review.issues,
                "questions": review.questions,
                "evidence": review.evidence,
                "preflight": preflight,
                "output": str(args.output) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
