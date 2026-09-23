#!/usr/bin/env python3
"""Run the real DeepSeek Agent 2 against an Agent 1 DatasetBlueprint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "back"
sys.path.insert(0, str(BACKEND_ROOT))

from app.agent_import.model_provider import AgentModelContext, ConfiguredAgentModelProvider  # noqa: E402
from app.agent_import.binary_executor import execute_binary_plan  # noqa: E402
from app.agent_import.contracts import AgentCandidatePlan  # noqa: E402
from app.agent_import.mapping_preflight import preflight_mapping_plan  # noqa: E402
from app.agent_import.research_contracts import AgentResearchResult  # noqa: E402
from app.agent_import.source_sampling import summarize_source_root  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.dataset_capabilities import compile_semantic_capability_report, get_view_catalog  # noqa: E402
from app.declarative_ingest import read_semantic_zp  # noqa: E402
from app.fingerprint import compute_dataset_metadata_fingerprint  # noqa: E402


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
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--user-message", action="append", default=[])
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--execute-root", type=Path)
    args = parser.parse_args()

    source = args.source.expanduser().resolve(strict=True)
    research = AgentResearchResult.model_validate_json(
        args.blueprint.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    )
    summary = summarize_source_root(source)
    context = AgentModelContext(
        case_id="live-deepseek-single-sample",
        context_revision=1,
        source_root=str(source),
        analysis_category="AUTO",
        requested_source_profile=research.blueprint.source_profile,
        format_details="Implement the approved Agent 1 DatasetBlueprint without dropping content.",
        dataset_fingerprint="0" * 32,
        source_summary=summary,
        user_messages=list(args.user_message),
    )
    strategy = {
        "schema_version": 3,
        "decision": "BLUEPRINT_READY",
        "analysis_category": "AUTO",
        "proposed_source_profile": research.blueprint.source_profile,
        **research.model_dump(mode="json"),
    }
    plan = (
        AgentCandidatePlan.model_validate_json(
            args.candidate.expanduser().resolve(strict=True).read_text(encoding="utf-8")
        )
        if args.candidate
        else ConfiguredAgentModelProvider().build_candidate(context, strategy)
    )
    trusted_observations = {item.call_id: item.payload for item in research.observations}
    trusted_observations.update(
        {
            f"user-message:{index}": {"kind": "user_input", "text": message}
            for index, message in enumerate(args.user_message, 1)
        }
    )
    preflight = (
        preflight_mapping_plan(
            source_root=source,
            plan=plan,
            allow_legacy_mapping=False,
            trusted_observations=trusted_observations,
        )
        if plan.status == "READY"
        else None
    )
    if plan.status == "READY":
        if plan.schema_version != 3 or plan.zp_conversion_plan is None:
            raise AssertionError("Agent 2 did not produce the schema v3 declarative protocol")
        if plan.zp_conversion_plan.declarative_plan is None:
            raise AssertionError("Agent 2 fell back to a legacy named mapping adapter")
        if plan.physical_analysis_mode != "BOTTOM_UP":
            raise AssertionError("Agent 2 did not preserve the inferred BOTTOM_UP physical mode")
    execution = None
    if args.execute_root and plan.status == "READY":
        settings.zp_output_root = args.execute_root.expanduser().resolve(strict=False)
        fingerprint = compute_dataset_metadata_fingerprint(source).fingerprint
        executed = execute_binary_plan(
            case_id="live-deepseek-single-sample-v3",
            source_root=source,
            source_fingerprint=fingerprint,
            plan=plan,
            trusted_observations=trusted_observations,
        )
        semantic = read_semantic_zp(executed.zp_path)
        report = compile_semantic_capability_report(
            dataset_id=1,
            source_case_id="live-deepseek-single-sample-v3",
            semantic=semantic,
            requested_view_ids=list(
                dict.fromkeys(
                    [
                        *(item.view_id for item in get_view_catalog("BOTTOM_UP")),
                        *semantic.requested_view_ids,
                    ]
                )
            ),
        )
        execution = {
            "zp_path": str(executed.zp_path),
            "zp_sha256": executed.output_sha256,
            "validation_mode": executed.validation_mode,
            "core_spectrum_count": semantic.core_spectrum_count,
            "core_chromatogram_count": semantic.core_chromatogram_count,
            "semantic_verification": executed.semantic_verification,
            "views": {item.view_id: item.availability for item in report.views},
            "missing_inputs": [item.model_dump(mode="json") for item in report.missing_inputs],
        }
    payload = plan.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        target = args.output.expanduser().resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "model": settings.openai_model,
                "status": plan.status,
                "source_profile": plan.source_profile,
                "binary_operation": plan.binary_operation,
                "questions": plan.questions,
                "preflight": preflight,
                "execution": execution,
                "output": str(args.output) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
