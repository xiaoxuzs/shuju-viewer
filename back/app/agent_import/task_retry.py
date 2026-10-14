"""User-requested retry of an unpublished ordinary task, with immutable history."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from sqlalchemy import text

from .errors import AgentImportError
from .input_assets import content_manifest
from .task_runtime import TaskRuntime, effective_policy


def reverify_candidate(service, case_id, expected_version):
    """Recheck the unchanged unpublished candidate; never call a model or reset usage."""
    from .states import CaseStatus, assert_transition
    with service.engine.begin() as db:
        current = service._locked_case(db, case_id)
        if (current.status != CaseStatus.READY_FOR_REVIEW or current.version != expected_version
                or current.lease_owner or current.stop_requested_at or current.ever_published
                or current.dataset_id is not None or not current.candidate_payload or not current.candidate_zp_sha256):
            raise AgentImportError("TASK_REVERIFY_STATE_CONFLICT", "Only an unchanged, unpublished reviewed candidate can be reverified", status_code=409)
        assert_transition(current.status, CaseStatus.VERIFYING)
        now = datetime.now(timezone.utc).isoformat()
        service._insert_json_artifact_tx(db, current, None, "verification_refresh", {
            "candidate_sha256": current.candidate_zp_sha256, "previous_verification": current.verification_payload,
            "context_revision": current.context_revision, "model_requests": 0}, now)
        db.execute(text("UPDATE agent_import_cases SET status='VERIFYING',version=version+1,progress_payload=NULL,updated_at=:now WHERE case_id=:id"),
            {"id": case_id, "now": now})
        service._append_message(db, case_id=case_id, context_revision=current.context_revision, sender_type="SYSTEM", message_kind="STATUS",
            content="Rechecking the existing reviewed ZP against the current application; no model plan regeneration or budget reset.",
            payload={"event": "verification_refresh", "candidate_sha256": current.candidate_zp_sha256}, created_at=now)
    return service.get_case(case_id)


def retry_task(service, case_id, expected_version):
    case = service.get_case(case_id)
    if case.ever_published or case.dataset_id is not None or case.status.value not in {"FAILED", "NEEDS_USER"}:
        raise AgentImportError("TASK_RETRY_STATE_CONFLICT", "Only a failed unpublished task can retry; published data uses maintenance", status_code=409)
    if not case.source_content_sha256 or content_manifest(Path(case.source_ref))["sha256"] != case.source_content_sha256:
        raise AgentImportError("SOURCE_CHANGED", "Source content changed; reconcile it before retrying", status_code=409)
    with service.engine.begin() as db:
        runtime = TaskRuntime(service.engine, case_id)._lock(db)
        lock = " FOR UPDATE" if db.dialect.name == "postgresql" else ""
        current = db.execute(text("SELECT * FROM agent_import_cases WHERE case_id=:id"+lock), {"id": case_id}).mappings().one()
        if runtime["kind"] != "initial" or current["status"] not in {"FAILED", "NEEDS_USER"} or current["version"] != expected_version or current["ever_published"] or current["dataset_id"] is not None or current["lease_owner"]:
            raise AgentImportError("TASK_RETRY_STATE_CONFLICT", "Task changed or still has a Worker; retry was not applied", status_code=409)
        published = service._published_source_tx(db, owner_id=current["owner_id"], workspace_id=current["workspace_id"],
            dataset_fingerprint=current["dataset_fingerprint"], source_content_sha256=current["source_content_sha256"])
        if published is not None:
            # Preserve the failed task, its attempts and charged requests. There
            # is already a delivery for this source, so no new model run is needed.
            return published
        policy = effective_policy()
        # A newly requested run has normal server limits; previous consumption
        # stays charged and queryable, not reset or relabelled as unexecuted.
        policy["reservation_units"] += runtime["reserved_units"]
        policy["preview_bytes"] = max(policy["preview_bytes"], json.loads(runtime["policy_json"])["preview_bytes"])
        now = time.time()
        deadline = now + policy["task_seconds"]
        revision = current["context_revision"] + 1
        retained_strategy = current["strategy_payload"]
        previous_policy = json.loads(runtime["policy_json"])
        compatibility = None
        if retained_strategy:
            from .model_routing import model_route_identity
            if previous_policy["route_sha256"] != policy["route_sha256"]:
                raise AgentImportError("MODEL_ROUTE_CHANGED", "Model connection changed; retained research requires an explicit compatibility review", status_code=409)
            retained_strategy = json.loads(retained_strategy)
            compatibility = {"kind": "same_model_connection_new_execution_policy",
                "research_route_identity": retained_strategy.get("model_route_identity"),
                "execution_route_identity": model_route_identity(), "research_reexecuted": False}
            retained_strategy["research_reuse"] = compatibility
            retained_strategy["model_route_identity"] = model_route_identity()
        resume = "STRATEGY_READY" if retained_strategy else "CREATED"
        diagnostic = db.execute(text("SELECT payload_json FROM agent_artifacts WHERE case_id=:id AND artifact_type='candidate_diagnostic' ORDER BY created_at DESC LIMIT 1"), {"id": case_id}).scalar()
        feedback = None
        if diagnostic and retained_strategy:
            rejected = json.loads(diagnostic)
            feedback = {"candidate_repair_feedback": {"kind": "retained_candidate_rejection",
                "field_errors": rejected.get("errors"), "previous_candidate": rejected.get("candidate"),
                "instruction": "Use the current executor capabilities to correct the retained rejected candidate; do not repeat a rejected unsupported join or re-research already established facts."}}
        payload = {"event": "ordinary_task_retry", "previous_context_revision": current["context_revision"],
            "context_revision": revision, "previous_policy": json.loads(runtime["policy_json"]),
            "new_policy": policy, "previous_deadline": runtime["deadline_at"], "new_deadline": deadline,
            "request_count_preserved": runtime["request_count"], "reserved_units_preserved": runtime["reserved_units"],
            "preview_used_preserved": runtime["preview_used"], "source_content_sha256": case.source_content_sha256,
            "resume_at": resume, "research_reused": bool(retained_strategy),
            "compatibility": compatibility,
            "reason": "Explicit user retry after a failed ordinary run; no historical experiment recovery"}
        service._insert_json_artifact_tx(db, case, None, "task_retry", payload, datetime.now(timezone.utc).isoformat())
        db.execute(text("UPDATE agent_task_runs SET policy_json=:policy,deadline_at=:deadline,ended_at=NULL WHERE task_id=:id"),
            {"id": case_id, "policy": json.dumps(policy), "deadline": deadline})
        db.execute(text("""UPDATE agent_import_cases SET status=:state,context_revision=:revision,version=version+1,
            deadline_at=:deadline,stop_requested_at=NULL,candidate_payload=NULL,verification_payload=:feedback,
            candidate_zp_path=NULL,candidate_zp_sha256=NULL,authorization_wait_reason=NULL,progress_payload=NULL,
            strategy_payload=:strategy WHERE case_id=:id"""),
            {"id": case_id, "state": resume, "revision": revision,
             "strategy": json.dumps(retained_strategy) if retained_strategy else None,
             "feedback": json.dumps(feedback) if feedback else None,
             "deadline": datetime.fromtimestamp(deadline, timezone.utc).isoformat()})
        service._append_message(db, case_id=case_id, context_revision=revision, sender_type="SYSTEM", message_kind="STATUS",
            content="A new ordinary execution attempt was requested. Previous failures and request consumption are retained.", payload=payload,
            created_at=datetime.now(timezone.utc).isoformat())
    return service.get_case(case_id)
