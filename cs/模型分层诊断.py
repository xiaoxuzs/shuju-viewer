"""Explicit, bounded online diagnostics. Never reads database settings or logs bodies/keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorize-configured-models", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stages", action="store_true", help="Real provider plan, tool loop and review; synthetic fixture only")
    parser.add_argument("--contract-followup", action="store_true", help="Two-call GPT contract/review follow-up only")
    parser.add_argument("--research-followup", action="store_true", help="Six-call fresh GPT research/plan/review; bounded synthetic input")
    parser.add_argument("--synthesis-followup", action="store_true", help="At most two synthesis-only calls on retained synthetic observations")
    parser.add_argument("--configured-timeout-once", action="store_true", help="One synthesis request using the configured read timeout, without retries")
    args = parser.parse_args()
    if not args.authorize_configured_models:
        raise SystemExit("Explicit authorization required")
    root = Path(__file__).resolve().parents[1]
    from dotenv import dotenv_values
    values = dotenv_values(root / "back/.env")
    def get(name, default=""):
        return os.environ.get(name, values.get(name) or default)
    routes = [
        ("shared_api", get("OPENAI_BASE_URL"), get("OPENAI_API_KEY"), get("OPENAI_MODEL")),
    ]
    model_values = {name: get(name) for name in (
        "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")}
    values.clear()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(root / "back"))
    if args.configured_timeout_once:
        from dotenv import dotenv_values
        timeout_values = dotenv_values(root / "back/.env")
        model_values["OPENAI_REQUEST_TIMEOUT_SECONDS"] = os.environ.get("OPENAI_REQUEST_TIMEOUT_SECONDS", timeout_values.get("OPENAI_REQUEST_TIMEOUT_SECONDS") or "60")
        timeout_values.clear()
    if args.stages or args.contract_followup or args.research_followup or args.synthesis_followup or args.configured_timeout_once:
        passed = stages(root, args.output, model_values, followup=args.contract_followup, fresh=args.research_followup,
                        synthesis=args.synthesis_followup or args.configured_timeout_once, configured_once=args.configured_timeout_once)
        if not passed:
            raise SystemExit(1)
        return
    from app.agent_import.model_http import request_model_json
    from app.agent_import.model_diagnostics import describe_model_failure
    from app.agent_import.model_audit import diagnostic_budget
    records = []
    seen = set()
    for role, base, key, model in routes:
        identity = (base, model)
        if identity in seen:
            continue
        seen.add(identity)
        body = {"model": model, "messages": [{"role": "user", "content":
            'Return only JSON with keys records, zero, missing. For data [{"x":0},{"x":null}], report record count and count zero separately from missing.'}],
            "response_format": {"type": "json_object"}, "max_completion_tokens": 512}
        encoded = json.dumps(body, ensure_ascii=False).encode()
        record = {"role": role, "layer": "A", "request_model": model,
                  "protocol": "chat_completions", "config_fingerprint": hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                  "request_bytes": len(encoded), "message_count": 1, "output_limit": 512,
                  "retries": 0, "timeout_seconds": 60, "key_present": bool(key),
                  "code_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
                      "back/app/agent_import/model_http.py", "back/app/agent_import/model_http_worker.py")}}
        started = time.monotonic()
        try:
            if not all((base, key, model)):
                raise ValueError("Incomplete model configuration")
            telemetry = []
            with diagnostic_budget(telemetry.append, calls=1, seconds=60):
                response = request_model_json(base.rstrip("/") + "/chat/completions", method="POST", api_key=key, body=body, timeout=60, role=role)
            choice = response["choices"][0]
            content = choice["message"].get("content")
            record.update({"response_model": response.get("model"), "response_id": response.get("id"),
                           "finish_reason": choice.get("finish_reason"), "usage": response.get("usage"),
                           "transport": telemetry[-1].get("transport"), "refusal": bool(choice["message"].get("refusal"))})
            parsed = json.loads(content)
            record["passed"] = choice.get("finish_reason") == "stop" and not record["refusal"] and parsed == {"records": 2, "zero": 1, "missing": 1}
            record["json_parsed"] = True
        except Exception as exc:
            record.update({"passed": False, "error": describe_model_failure(exc, phase=role, endpoint="")})
        record["elapsed_seconds"] = time.monotonic() - started
        records.append(record)
        (args.output / "results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
    if not all(record["passed"] for record in records):
        raise SystemExit(1)


def stages(root: Path, output: Path, model_values: dict, *, followup=False, fresh=False, synthesis=False, configured_once=False) -> bool:
    temporary = Path(tempfile.mkdtemp(prefix="viewer-model-layers-"))
    data = temporary / "source"
    data.mkdir()
    (data / "unknown-results.tsv").write_text("record\trun\tsequence\tproteins\tintensity\none\trun-a\tPEPTIDE\tP1\t0\ntwo\trun-b\tANOTHER\tP2\t\n", encoding="utf-8")
    os.environ.update(model_values)
    os.environ.update({"VIEWER_ENV": "test", "DATABASE_URL": f"sqlite+pysqlite:///{(temporary / 'unused.sqlite').as_posix()}",
                       "DATA_ROOT": str(data), "AGENT_API_WORKER_ENABLED": "false", "AGENT_SOURCE_READ_ENABLED": "false",
                       "AGENT_READ_MAX_OUTPUT_TOKENS": "4096", "AGENT_IMPLEMENTATION_MAX_OUTPUT_TOKENS": "4096",
                       "AGENT_REVIEW_MAX_OUTPUT_TOKENS": "4096", "OPENAI_REQUEST_TIMEOUT_SECONDS": "90",
                       "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS": "90", "AGENT_REVIEW_REQUEST_TIMEOUT_SECONDS": "90",
                       "AGENT_RESEARCH_REASONING_EFFORT": "low"})
    from app.agent_import.model_provider import AgentModelContext, ConfiguredAgentModelProvider
    from app.agent_import.model_audit import diagnostic_budget
    from app.agent_import.execution_control import ExecutionFence, execution_scope
    from app.agent_import.errors import AgentImportError
    from app.agent_import.mapping_preflight import preflight_mapping_plan
    from app.agent_import.source_sampling import summarize_source_root
    from app.core.config import settings
    synthesis_timeout = int(model_values.get("OPENAI_REQUEST_TIMEOUT_SECONDS", "90")) if configured_once else 90
    if not 1 <= synthesis_timeout <= 180:
        raise ValueError("This diagnostic admits a configured timeout of at most 180 seconds")
    # Frozen historic material is synthetic and has no source-code observations.
    frozen_path = root / ".tmp/自动接入验收-20260916/真实模型-硬时限复验/model-artifacts.json"
    frozen = next(x["payload"] for x in json.loads(frozen_path.read_text(encoding="utf-8")) if x["type"] == "strategy")
    assert len(frozen.get("observations", [])) == 3
    assert not any(x.get("tool_name") in {"search_viewer_source", "read_viewer_source"} for x in frozen["observations"])
    rejected = []
    def rejection(record):
        rejected.append(record)
        (output / "rejected-candidates.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    context = AgentModelContext(case_id="synthetic-layered-diagnostic", context_revision=1, source_root=str(data), candidate_diagnostic_sink=rejection,
        analysis_category="BOTTOM_UP", requested_source_profile="synthetic unknown table",
        format_details="Synthetic fixture only. record identifies each PSM, run identifies the run, sequence is peptide, proteins is accession. intensity is source intensity. Preserve zero versus missing. No spectra, FASTA, confidence or decoy facts supplied.",
        dataset_fingerprint="0" * 32, source_summary=summarize_source_root(data), user_messages=[])
    calls, results = [], []
    deadline = time.monotonic() + 840
    def check(_amount):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AgentImportError("DIAGNOSTIC_DEADLINE", "Diagnostic wall clock expired", status_code=409)
        return remaining
    def sink(record):
        calls.append(record)
        (output / "http.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"call": len(calls), **record}, ensure_ascii=False), flush=True)
    def phase(name, callback):
        started = time.monotonic()
        try:
            value = callback()
            item = {"phase": name, "passed": True, "result": value.model_dump(mode="json") if hasattr(value, "model_dump") else value}
        except Exception as exc:
            item = {"phase": name, "passed": False, "error_type": type(exc).__name__, "code": getattr(exc, "code", None),
                    "diagnostics": getattr(exc, "diagnostics", None)}
            value = None
        item["elapsed_seconds"] = time.monotonic() - started
        results.append(item)
        (output / "phases.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k: v for k, v in item.items() if k != "result"}), flush=True)
        return value
    provider = ConfiguredAgentModelProvider(candidate_attempt_limit=1)
    with diagnostic_budget(sink, calls=1 if configured_once else 6 if fresh else 2 if followup or synthesis else 10, seconds=600 if fresh else 240 if followup or synthesis else 840), execution_scope(ExecutionFence("diagnostic", "diagnostic", check)):
        if synthesis:
            from app.agent_import.kimi_research_runtime import KimiResearchRuntime, _RESEARCH_SYSTEM_PROMPT
            from app.agent_import.research_contracts import DatasetBlueprint
            messages = [{"role": "system", "content": _RESEARCH_SYSTEM_PROMPT}, {"role": "user", "content": json.dumps({
                "analysis_category": "BOTTOM_UP", "format_details": context.format_details,
                "dataset_blueprint_json_schema": DatasetBlueprint.model_json_schema(),
                "requested_source_profile": context.requested_source_profile})}]
            messages += [{"role": "tool", "tool_call_id": o["call_id"], "name": o["tool_name"], "content": json.dumps(o["payload"])} for o in frozen["observations"]]
            runtime = KimiResearchRuntime(base_url=settings.openai_base_url, api_key=settings.openai_api_key,
                model=settings.openai_model, timeout=synthesis_timeout, max_output_tokens=4096, reasoning_effort="low")
            phase("gpt_synthesis_from_frozen_synthetic_tool_evidence_not_full_loop", lambda: runtime._parse_blueprint(None, messages))
            return all(p["passed"] for p in results)
        if fresh:
            fresh_strategy = phase("fresh_gpt_research", lambda: provider.analyze_source(context))
            if fresh_strategy is not None:
                fresh_candidate = phase("fresh_gpt_candidate", lambda: provider.build_candidate(context, fresh_strategy))
                if fresh_candidate is not None and fresh_candidate.status == "READY":
                    from app.agent_import.model_provider import _trusted_observations
                    report = preflight_mapping_plan(source_root=context.source_root, plan=fresh_candidate, allow_legacy_mapping=False,
                                                    trusted_observations=_trusted_observations(fresh_strategy))
                    phase("fresh_gpt_review", lambda: provider.review_candidate(context, fresh_strategy, fresh_candidate, report))
            return all(p["passed"] for p in results)
        candidate = phase("B_D_gpt_frozen_synthetic_plan", lambda: provider.build_candidate(context, frozen))
        if candidate is not None and candidate.status == "READY":
            from app.agent_import.model_provider import _trusted_observations
            preflight = preflight_mapping_plan(source_root=context.source_root, plan=candidate, allow_legacy_mapping=False,
                                              trusted_observations=_trusted_observations(frozen))
            phase("D_gpt_review", lambda: provider.review_candidate(context, frozen, candidate, preflight))
        if not followup:
            phase("C_gpt_real_research_tool_loop", lambda: provider.analyze_source(context))
    return all(p["passed"] for p in results)


if __name__ == "__main__":
    main()
