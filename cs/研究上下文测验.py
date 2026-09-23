"""Bounded local research-context measurement; no model or database connection."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def collect(source):
    from app.agent_import.research_tools import AgentResearchToolbox
    tools = AgentResearchToolbox(source)
    results = []
    inventory = tools.execute("list_source_inventory", {"limit": 100})
    if inventory.get("next_cursor"):
        raise ValueError("This bounded diagnostic requires at most one inventory page")
    results.append(("list_source_inventory", inventory))
    for item in inventory["items"]:
        if item.get("kind") == "file":
            path = item["relative_path"]
            results.append(("inspect_source_file", tools.execute("inspect_source_file", {"relative_path": path})))
            if path.lower().endswith(".mzml"):
                results.append(("inspect_mzml", tools.execute("inspect_mzml", {"relative_path": path})))
            if path.lower().endswith((".fasta", ".fa", ".faa")):
                results.append(("inspect_fasta", tools.execute("inspect_fasta", {"relative_path": path})))
    results.append(("inspect_viewer_capabilities", tools.execute("inspect_viewer_capabilities", {})))
    return [{"call_id": "measured-"+str(i), "tool_name": name, "result": value} for i,(name,value) in enumerate(results)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--live-synthesis", action="store_true", help="Exactly one real synthesis request, no Case recovery or import")
    parser.add_argument("--output", type=Path, help="New diagnostic evidence directory")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    configured = {}
    if args.live_synthesis:
        from dotenv import dotenv_values
        values = dotenv_values(root / "back/.env")
        configured = {key: os.environ.get(key) or values.get(key) for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")}
        values.clear()
        if not args.output or not all(configured.values()):
            raise SystemExit("Current single model connection and a new evidence directory are required")
    scratch = Path(tempfile.mkdtemp(prefix="viewer-context-measure-"))
    os.environ.update(VIEWER_ENV="test", DATABASE_URL="sqlite+pysqlite:///"+(scratch/"unused.sqlite").as_posix(), DATA_ROOT=str(scratch))
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.update(configured)
    sys.path.insert(0, str(root/"back"))
    from app.agent_import.model_context import size, compact_research_evidence
    evidence = collect(source)
    report = {"model_requests": 0, "scope": "local bounded source inspection; never a replay of unretained historical tool arguments",
        "evidence_bytes": size(evidence), "compact_evidence_bytes": size(compact_research_evidence(evidence)),
        "tools": [{"tool": e["tool_name"], "path": e["result"].get("relative_path"),
            "bytes": size(e["result"]), "compact_bytes": size(compact_research_evidence(e["result"]))} for e in evidence]}
    if args.live_synthesis:
        args.output.mkdir(parents=True, exist_ok=False)
        from sqlalchemy import create_engine
        from app.agent_import.case_service import CaseService
        from app.agent_import.migrations import ensure_agent_import_schema
        from app.agent_import.task_runtime import TaskRuntime, task_scope
        from app.agent_import.execution_control import ExecutionFence, execution_scope
        from app.agent_import.model_audit import diagnostic_budget
        from app.agent_import.kimi_research_runtime import KimiResearchRuntime, _RESEARCH_SYSTEM_PROMPT, _strip_json_fence
        from app.agent_import.research_contracts import DatasetBlueprint
        from app.agent_import.source_sampling import summarize_source_root
        from app.agent_import.model_context import manifest_view
        from app.fingerprint import compute_dataset_metadata_fingerprint
        from pydantic import ValidationError
        engine = create_engine(os.environ["DATABASE_URL"])
        ensure_agent_import_schema(engine)
        service = CaseService(engine)
        case = service.create_case(source_ref=str(source), dataset_fingerprint=compute_dataset_metadata_fingerprint(source).fingerprint,
            analysis_category="AUTO", source_profile="Unknown format", format_details=None, owner_id="local-diagnostic")
        claimed = service.claim_next(worker_id="single-synthesis-diagnostic")
        runtime = KimiResearchRuntime(base_url=configured["OPENAI_BASE_URL"], api_key=configured["OPENAI_API_KEY"], model=configured["OPENAI_MODEL"], timeout=180, max_output_tokens=4096)
        real_transport = runtime.transport
        responses = []
        class Capture:
            def request_json(self, *a, **kw):
                result = real_transport.request_json(*a, **kw)
                responses.append(result)
                return result
        runtime.transport = Capture()
        messages = [{"role": "system", "content": _RESEARCH_SYSTEM_PROMPT}, {"role": "user", "content": json.dumps({
            "task": "Research this dataset and design its logical binary and visualization blueprint.", "case_id": case.case_id,
            "analysis_category": "AUTO", "requested_source_profile": "Unknown format", "format_details": None, "user_messages": [],
            "source_manifest": manifest_view(summarize_source_root(str(source))), "dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema()}, ensure_ascii=False)}]
        messages.extend({"role": "tool", "tool_call_id": e["call_id"], "name": e["tool_name"], "content": json.dumps(e["result"], ensure_ascii=False)} for e in evidence)
        audit = []
        policy = TaskRuntime(engine, case.case_id)
        fence = ExecutionFence(case.case_id, claimed.lease_token, lambda amount: service.check_execution(case.case_id, claimed.lease_token, amount))
        started = time.monotonic()
        report.update(scope="one real synthesis call using independently re-inspected bounded source evidence; NOT original Case recovery or full product acceptance",
            related_case="6bd93504-78a1-41c6-81f0-8702eb60896a", diagnostic_case=case.case_id, blueprint_valid=False)
        try:
            with diagnostic_budget(audit.append, calls=1, seconds=180), execution_scope(fence), task_scope(policy):
                blueprint = runtime._parse_blueprint(None, messages)
            (args.output / "blueprint.json").write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
            report["blueprint_valid"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error_code"] = getattr(exc, "code", None)
            if responses:
                choice = (responses[-1].get("choices") or [{}])[0]
                try:
                    DatasetBlueprint.model_validate_json(_strip_json_fence((choice.get("message") or {}).get("content") or ""))
                except ValidationError as validation:
                    report["outcome"] = "BLUEPRINT_VALIDATION_FAILED_AFTER_HTTP_RESPONSE"
                    from app.agent_import.model_diagnostics import redact_diagnostic
                    report["blueprint_validation_errors"] = redact_diagnostic(validation.errors(include_input=False, include_context=False, include_url=False)[:10], secrets=(configured["OPENAI_API_KEY"],))
                    content = (choice.get("message") or {}).get("content")
                    if isinstance(content, str) and len(content.encode()) <= 256 * 1024:
                        (args.output / "invalid-blueprint-redacted.json").write_text(json.dumps(redact_diagnostic(
                            {"visible_content": content}, secrets=(configured["OPENAI_API_KEY"],)), ensure_ascii=False), encoding="utf-8")
        finally:
            policy.end()
            engine.dispose()
        report.update(model_requests=len(audit), elapsed_seconds=time.monotonic()-started, request_audit=audit)
        (args.output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.live_synthesis and not report["blueprint_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
