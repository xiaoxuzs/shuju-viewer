"""Existing Worker consumer for independent published-context planning/execution.

Mapping candidates are compiled, independently verified and published as revisions.
Code requests never execute on the host.
"""
import json
import time
import uuid

from sqlalchemy import text

from .task_runtime import TaskRuntime, task_scope
from .errors import AgentImportError
from .execution_control import ExecutionFence, execution_scope, checkpoint
from .maintenance import propose_maintenance_plan, check_task_fence


def _claim(service):
    with service.engine.begin() as db:
        # Expired operations are reconciled, never replayed with reset limits.
        db.execute(text("UPDATE agent_maintenance_tasks SET state='RECONCILIATION_REQUIRED',wait_reason='EXPIRED_UNRECONCILED_OPERATION' WHERE state='RUNNING' AND lease_until<=:now"), {"now": time.time()})
        lock = " FOR UPDATE SKIP LOCKED" if db.dialect.name == "postgresql" else ""
        task = db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE state='QUEUED' ORDER BY created_at LIMIT 1" + lock)).mappings().first()
        if task is None:
            return None
        deadline = db.execute(text("SELECT deadline_at FROM agent_task_runs WHERE task_id=:id"), {"id": task["task_id"]}).scalar_one()
        parent = db.execute(text("SELECT ever_published,dataset_id FROM agent_import_cases WHERE case_id=:id"), {"id": task["parent_case_id"]}).mappings().first()
        reason = None
        if not parent or not parent["ever_published"] or not task["ever_published"] or parent["dataset_id"] != task["dataset_id"]:
            reason = "MAINTENANCE_REQUIRES_PUBLISHED_CONTEXT"
        elif deadline <= time.time():
            reason = "TASK_RUN_LIMIT_REACHED"
        if reason:
            db.execute(text("UPDATE agent_maintenance_tasks SET state='FAILED',wait_reason=:reason WHERE task_id=:id"), {"id": task["task_id"], "reason": reason})
            return None
        token = str(uuid.uuid4())
        db.execute(text("UPDATE agent_maintenance_tasks SET state='RUNNING',lease_token=:token,lease_until=:end,wait_reason=NULL WHERE task_id=:id"),
            {"id": task["task_id"], "token": token, "end": deadline})
        return {**task, "lease_token": token}

def consume_once(service):
    task = _claim(service)
    if task is None:
        return False
    runtime = TaskRuntime(service.engine, task["task_id"])
    def check(_):
        with service.engine.connect() as db:
            return check_task_fence(db, task["task_id"], fence)
    fence = ExecutionFence(task["task_id"], task["lease_token"], check)
    state, decision, candidate_path, candidate_sha, error = "FAILED", None, None, None, None
    try:
        with task_scope(runtime), execution_scope(fence):
            # These helpers are pure context/evidence guards, not Agent2 role entries.
            from .workflow import _assert_source_unchanged, _execution_source, _trusted_observations
            from .binary_executor import execute_binary_plan
            parent = service.get_case(task["parent_case_id"])
            strategy = parent.strategy_payload or {}
            if strategy.get("input_snapshot"):
                from pathlib import Path
                from .input_assets import content_manifest
                if content_manifest(Path(_execution_source(parent))) != strategy["input_snapshot"]:
                    raise AgentImportError("SOURCE_CHANGED", "Retained source content changed after publication.", status_code=409)
            else:
                _assert_source_unchanged(parent)
            with service.engine.connect() as db:
                previous = db.execute(text("SELECT candidate_json FROM agent_maintenance_tasks WHERE parent_case_id=:case AND published_revision_id=:revision AND state='PUBLISHED'"),
                    {"case": parent.case_id, "revision": task["revision_id"]}).scalar()
            decision = propose_maintenance_plan({"ever_published": True, "feedback": json.loads(task["feedback_json"])["feedback"],
                "published_context": {k: task[k] for k in ("parent_case_id", "dataset_id", "revision_id", "context_sha256")},
                "candidate": json.loads(previous) if previous else parent.candidate_payload,
                "blueprint": strategy.get("blueprint"), "observations": strategy.get("observations", [])})
            checkpoint()
            state = decision.status
            if state == "MAPPING_PLAN":
                compiled = execute_binary_plan(case_id=task["task_id"], source_root=_execution_source(parent), source_fingerprint=parent.dataset_fingerprint,
                    plan=decision.candidate, trusted_observations=_trusted_observations(strategy))
                candidate_path, candidate_sha = str(compiled.zp_path), compiled.output_sha256
                if parent.strategy_payload and parent.strategy_payload.get("input_snapshot"):
                    from .maintenance_publication import publish_repair
                    publish_repair(service, task, parent, decision, compiled, fence)
                    state = "PUBLISHED"
                else:
                    state = "AWAITING_REVISION_VALIDATION"
            elif state == "ENGINEERING_REQUIRED":
                state = "ENGINEERING_BLOCKED"  # never invokes initial engineering or executes generated code
            if state != "PUBLISHED":
                checkpoint()
    except Exception as exc:
        state = "FAILED"
        error = str(getattr(exc, "code", None) or type(exc).__name__)
    finally:
        try:
            if state == "PUBLISHED":
                return True
            with service.engine.begin() as db:
                try:
                    check_task_fence(db, task["task_id"], fence)
                except AgentImportError:
                    # Late results never become accepted candidates.
                    db.execute(text("UPDATE agent_maintenance_tasks SET state='RECONCILIATION_REQUIRED',wait_reason='LATE_RESULT_REJECTED' WHERE task_id=:id AND lease_token=:token AND state='RUNNING'"), {"id": task["task_id"], "token": task["lease_token"]})
                else:
                    db.execute(text("""UPDATE agent_maintenance_tasks SET state=:state,decision_json=:decision,candidate_json=:candidate,
                        candidate_path=:path,candidate_sha256=:sha,wait_reason=:error,lease_token=NULL,lease_until=NULL WHERE task_id=:id AND lease_token=:token"""),
                        {"id": task["task_id"], "token": task["lease_token"], "state": state, "decision": decision.model_dump_json() if decision else None,
                         "candidate": decision.candidate.model_dump_json() if decision and decision.candidate else None,
                         "path": candidate_path, "sha": candidate_sha, "error": error})
        finally:
            runtime.end()
    return True
