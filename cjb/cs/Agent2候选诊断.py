"""复用已有 Case Blueprint 单独诊断 Agent 2，不更新 Case、不生成 ZP、不导入数据。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))

from app.agent_import.case_service import CaseService
from app.agent_import.errors import AgentImportError
from app.agent_import.model_diagnostics import redact_diagnostic
from app.agent_import.model_provider import AgentModelContext, ConfiguredAgentModelProvider
from app.agent_import.source_sampling import summarize_source_root
from app.core.config import settings
from app.fingerprint import compute_dataset_metadata_fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists; choose a new diagnostic output filename.")
    service = CaseService()
    case = service.get_case(args.case_id)
    if case.strategy_payload is None:
        raise SystemExit("The Case has no saved Blueprint.")
    if not (settings.deepseek_api_key or "").strip():
        raise SystemExit("Agent 2 provider is not configured.")
    fingerprint = compute_dataset_metadata_fingerprint(case.source_ref).fingerprint
    if fingerprint != case.dataset_fingerprint:
        raise SystemExit("Source changed; diagnostic stopped without calling a model.")
    secrets = tuple(value for value in (settings.moonshot_api_key, settings.deepseek_api_key, case.source_ref) if value)
    result = {"case_id": case.case_id, "context_revision": case.context_revision,
              "model": settings.agent_implementation_model, "status": "RUNNING", "candidate_attempts": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        def save() -> None:
            stream.seek(0)
            json.dump(redact_diagnostic(result, secrets=secrets), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.truncate()
            stream.flush()

        def record(payload: dict) -> None:
            result["candidate_attempts"].append(payload)
            save()
            print(json.dumps({key: payload[key] for key in ("candidate_attempt", "kind", "errors")}, ensure_ascii=True), flush=True)

        context = AgentModelContext(
            case_id=case.case_id, context_revision=case.context_revision, source_root=case.source_ref,
            analysis_category=case.analysis_category, requested_source_profile=case.source_profile,
            format_details=case.format_details, dataset_fingerprint=case.dataset_fingerprint,
            source_summary=summarize_source_root(case.source_ref),
            user_messages=[item.content for item in service.list_messages(case.case_id) if item.sender_type == "USER"][-20:],
            candidate_diagnostic_sink=record,
        )
        save()
        print(json.dumps({"event": "agent_2_only_started", "model": settings.agent_implementation_model,
                          "context_revision": case.context_revision, "attempt_limit": args.attempts}), flush=True)
        started = time.monotonic()
        try:
            plan = ConfiguredAgentModelProvider(candidate_attempt_limit=args.attempts).build_candidate(context, case.strategy_payload)
            result["status"] = plan.status
            result["candidate"] = plan.model_dump(mode="json")
            result["questions"] = plan.questions
        except AgentImportError as exc:
            result.update(status="REJECTED", error_code=exc.code, error_message=exc.message, diagnostics=exc.diagnostics)
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        unchanged = service.get_case(case.case_id)
        result["case_unchanged"] = unchanged.version == case.version and unchanged.status == case.status
        save()
    print(json.dumps({key: value for key, value in result.items() if key not in {"candidate", "candidate_attempts"}}, ensure_ascii=True), flush=True)
    return 0 if result["status"] in {"READY", "NEEDS_USER", "UNSUPPORTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
