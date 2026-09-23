"""Guarded unpublished execution recovery, preserving the Case budget and original evidence."""
from datetime import datetime, timezone
import hashlib
import json
import os

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentImportError
from app.agent_import.research_tools import AgentResearchToolbox
from app.agent_import.source_code import SourceSnapshot, canonical_bytes, digest_bytes
from app.agent_import.states import CaseStatus
from app.core.config import settings

_ADMITTED_RECOVERY_CHANGES = {
    "back/app/agent_import/recovery.py", "back/app/agent_import/case_service.py", "back/app/agent_import/states.py",
    "back/app/agent_import/failure_policy.py", "back/app/agent_import/graph.py", "back/app/agent_import/workflow.py",
    "back/app/agent_import/model_provider.py", "back/app/agent_import/api.py", "back/app/agent_import/schemas.py",
    "back/app/source_inspection/registered.py", "back/app/declarative_ingest/preflight.py",
    "back/tests/test_agent_execution_recovery.py",
}


def recover_execution(service, case_id, *, expected_version, new_code_identity):
    from app.agent_import.workflow import _assert_model_routes, _assert_source_unchanged, _execution_source
    if os.environ.get("VIEWER_ENV") != "test" or settings.agent_api_worker_enabled or len(settings.agent_internal_token or "") < 32:
        raise AgentImportError("RECOVERY_NOT_AUTHORIZED", "Recovery is restricted to the explicit local test runtime", status_code=403)
    case = service.get_case(case_id)
    if case.status != CaseStatus.FAILED or case.version != expected_version or case.ever_published or case.dataset_id is not None:
        raise AgentImportError("RECOVERY_STATE_CONFLICT", "Only the unchanged unpublished failed Case can be recovered", status_code=409)
    if not case.deadline_at or datetime.fromisoformat(case.deadline_at) <= datetime.now(timezone.utc):
        raise AgentImportError("AGENT_DEADLINE_EXCEEDED", "Recovery cannot reset an expired original task budget", status_code=409)
    _assert_model_routes(case)
    _assert_source_unchanged(case)
    plan = AgentCandidatePlan.model_validate(case.candidate_payload)
    if plan.status != "READY" or plan.binary_operation != "convert_declared_mapping_to_zp":
        raise AgentImportError("RECOVERY_NOT_SUPPORTED", "Recovery requires the retained executable declarative candidate", status_code=409)
    failures = [a for a in service.list_attempts(case_id) if a.failure_code in {"DECLARATIVE_EXECUTION_FAILED", "ADAPTER_FIELD_MAPPING_FAILED"}]
    if not failures:
        raise AgentImportError("RECOVERY_NOT_SUPPORTED", "No retained mapping-execution failure supports this recovery", status_code=409)
    snapshot = SourceSnapshot.capture(settings.agent_source_root)
    previous = (case.strategy_payload or {}).get("source_snapshot") or {}
    files = previous.get("files") or {}
    if snapshot.identity != new_code_identity or not files:
        raise AgentImportError("SOURCE_CODE_CHANGED", "Recovery needs exact previous and current code identities", status_code=409)
    changed = {p for p in set(files) | set(snapshot.manifest) if files.get(p) != snapshot.manifest.get(p)}
    if changed - _ADMITTED_RECOVERY_CHANGES:
        raise AgentImportError("SOURCE_CODE_CHANGED", "Changed conversion/projection/verification code needs a separate revalidation, not this recovery", status_code=409,
            diagnostics={"unadmitted_files": sorted(changed - _ADMITTED_RECOVERY_CHANGES)})
    strategy = dict(case.strategy_payload)
    observations = list(strategy.get("observations", []))
    toolbox = AgentResearchToolbox(_execution_source(case))
    for source in plan.zp_conversion_plan.declarative_plan.sources:
        if source.reader in {"parquet", "delimited", "jsonl"}:
            payload = toolbox.execute("inspect_source_file", {"relative_path": source.relative_path})
            call_id = "recovery-source-" + digest_bytes(source.relative_path.encode())[:16]
            observations.append({"call_id": call_id, "tool_name": "inspect_source_file", "status": "SUCCEEDED",
                "result_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(), "payload": payload})
    strategy.update(observations=observations, source_snapshot={"sha256": snapshot.identity, "files": snapshot.manifest})
    feedback = {"kind": "retained_execution_failure", "previous_candidate": case.candidate_payload,
        "failure_code": failures[-1].failure_code,
        "instruction": "Repair the retained candidate using the new full-source missing-value observations. Missing protein groups are optional source facts, not a reason to drop identification rows or fabricate groups. Do not repeat directory research or relax the data contract."}
    recovery = {"old_code": previous.get("sha256"), "new_code": snapshot.identity, "changed_files": sorted(changed),
        "context_revision": case.context_revision, "deadline_at_preserved": case.deadline_at,
        "reserved_budget_preserved": case.model_tokens_reserved, "reuse": "unchanged frozen source, requirements, model route and scientific converters; candidate and review will be regenerated"}
    updated = service._transition(case, CaseStatus.STRATEGY_READY, content="Operator-authorized repair resumes at the candidate step with full-source missingness evidence; original budgets retained.",
        payload={"event": "execution_recovery", **recovery}, sender_type="SYSTEM", release_lease=True,
        updates={"strategy_payload": json.dumps(strategy, ensure_ascii=False), "verification_payload": json.dumps({"candidate_repair_feedback": feedback})})
    service._record_json_artifact(case_id, "execution_recovery", recovery)
    return updated
