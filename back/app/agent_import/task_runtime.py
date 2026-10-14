"""Ordinary task policy and body-free request journal, NOT model grants.

Policy comes from existing server settings at task creation. Authentication is
handled by the API, model credentials by the single configured connection, and
runtime checks here preserve fencing, limits and audit without an approval step.
Historical experiments continue to use AuthorizationLedger only explicitly.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import time
import uuid

from sqlalchemy import text

from .authorization_ledger import canonical, route_identity
from .errors import AgentImportError

DDL = (
    """CREATE TABLE IF NOT EXISTS agent_task_runs (
        task_id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent_case_id TEXT NULL,
        policy_json TEXT NOT NULL, deadline_at DOUBLE PRECISION NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0, reserved_units BIGINT NOT NULL DEFAULT 0,
        preview_used BIGINT NOT NULL DEFAULT 0, serial INTEGER NOT NULL DEFAULT 0,
        created_at DOUBLE PRECISION NOT NULL, ended_at DOUBLE PRECISION NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_task_requests (
        request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES agent_task_runs(task_id),
        role TEXT NOT NULL, reserved_units BIGINT NOT NULL, request_sha256 TEXT NOT NULL,
        outcome TEXT NOT NULL, started_at DOUBLE PRECISION NOT NULL, result_json TEXT NULL)""",
)


def fail(code, message):
    raise AgentImportError(code, message, status_code=409)


def effective_policy():
    from app.core.config import settings
    from .model_context import MAX_REQUEST_BYTES, MAX_TOOL_SESSION_BYTES
    # No new global request count or experiment-minute limit. Existing names
    # remain compatible; reservation units have never meant billed tokens.
    roles = {
        "research": (settings.openai_request_timeout_seconds, settings.agent_read_max_output_tokens),
        "implementation": (settings.agent_implementation_request_timeout_seconds or settings.openai_request_timeout_seconds, settings.agent_implementation_max_output_tokens),
        "review": (settings.agent_review_request_timeout_seconds, settings.agent_review_max_output_tokens),
        "maintenance": (settings.agent_maintenance_request_timeout_seconds, settings.agent_maintenance_max_output_tokens),
    }
    return {"schema_version": 1, "origin": "server_task_settings", "task_seconds": settings.agent_case_deadline_seconds,
        "reservation_units": settings.agent_case_token_budget, "reservation_unit_definition": "UTF-8 request bytes plus maximum output allowance; not billed tokens",
        "memory_bytes": settings.agent_case_process_memory_budget_bytes, "preview_bytes": MAX_TOOL_SESSION_BYTES,
        "request_bytes": MAX_REQUEST_BYTES,
        "route_sha256": route_identity(settings.openai_base_url.rstrip("/")+"/chat/completions", settings.openai_model),
        "roles": {role: {"timeout_seconds": limits[0], "output_limit": limits[1]} for role, limits in roles.items()}}


def create_task_tx(db, task_id, *, kind="initial", parent_case_id=None, deadline=None):
    policy = effective_policy()
    now = time.time()
    deadline = deadline or now + policy["task_seconds"]
    db.execute(text("""INSERT INTO agent_task_runs(task_id,kind,parent_case_id,policy_json,deadline_at,created_at)
        VALUES(:id,:kind,:parent,:policy,:deadline,:now)"""),
        {"id": task_id, "kind": kind, "parent": parent_case_id, "policy": canonical(policy), "deadline": deadline, "now": now})


class TaskRuntime:
    def __init__(self, engine, task_id):
        self.engine, self.task_id = engine, task_id

    def exists(self):
        with self.engine.connect() as db:
            return db.execute(text("SELECT 1 FROM agent_task_runs WHERE task_id=:id"), {"id": self.task_id}).first() is not None

    def _lock(self, db):
        if db.execute(text("UPDATE agent_task_runs SET serial=serial+1 WHERE task_id=:id"), {"id": self.task_id}).rowcount != 1:
            fail("TASK_RUNTIME_REQUIRED", "The task has no recorded execution policy")
        return db.execute(text("SELECT * FROM agent_task_runs WHERE task_id=:id"), {"id": self.task_id}).mappings().one()

    def _check(self, db, row):
        from .execution_control import current_fence
        fence = current_fence()
        if fence is None or fence.case_id != self.task_id:
            fail("WORKER_LEASE_LOST", "A current task execution lease is required")
        now = time.time()
        remaining = row["deadline_at"] - now
        if row["ended_at"] is not None or remaining <= 0:
            fail("TASK_RUN_LIMIT_REACHED", "达到任务运行上限；任务截止时间已到")
        memory = json.loads(row["policy_json"])["memory_bytes"]
        if memory:
            from .verification_metrics import peak_rss_bytes
            observed = peak_rss_bytes(current=True)
            if observed is None or observed > memory:
                fail("AGENT_MEMORY_BUDGET_EXCEEDED", "Task process memory limit reached")
        if row["kind"] == "maintenance":
            from .maintenance import check_task_fence
            remaining = min(remaining, check_task_fence(db, self.task_id, fence) or 0)
            parent = db.execute(text("SELECT ever_published,dataset_id FROM agent_import_cases WHERE case_id=:id"), {"id": row["parent_case_id"]}).mappings().first()
            task = db.execute(text("SELECT dataset_id,ever_published FROM agent_maintenance_tasks WHERE task_id=:id"), {"id": self.task_id}).mappings().one()
            if not parent or not parent["ever_published"] or not task["ever_published"] or parent["dataset_id"] != task["dataset_id"]:
                fail("MAINTENANCE_REQUIRES_PUBLISHED_CONTEXT", "Maintenance must retain its published dataset lineage")
            return remaining, True
        lock = " FOR UPDATE" if db.dialect.name == "postgresql" else ""
        case = db.execute(text("SELECT * FROM agent_import_cases WHERE case_id=:id" + lock), {"id": self.task_id}).mappings().one()
        if case["lease_token"] != fence.token or not case["lease_owner"] or not case["lease_expires_at"] or datetime.fromisoformat(case["lease_expires_at"]).timestamp() <= now:
            fail("WORKER_LEASE_LOST", "The Worker lease is expired or superseded")
        if case["stop_requested_at"] or case["status"] in {"STOPPING", "STOPPED", "FAILED", "SUCCESS"}:
            fail("AGENT_CANCELLED", "The task is cancelled or no longer executable")
        remaining = min(remaining, datetime.fromisoformat(case["deadline_at"]).timestamp()-now)
        if remaining <= 0:
            fail("TASK_RUN_LIMIT_REACHED", "达到任务运行上限；任务截止时间已到")
        # Only maintenance tasks inherit a parent's publication (checked above).
        # Older initial tasks linked same-content copies to a published parent;
        # that historical reference does not publish this independent dataset.
        published = bool(case["ever_published"] or case["dataset_id"] is not None)
        return remaining, published

    def check(self):
        with self.engine.begin() as db:
            return self._check(db, self._lock(db))[0]

    def reserve(self, *, role, route_sha256, request_bytes, output_limit, request_sha256, request_id=None):
        if request_bytes < 0 or output_limit <= 0:
            raise ValueError("Invalid request accounting")
        with self.engine.begin() as db:
            row = self._lock(db)
            remaining, published = self._check(db, row)
            policy = json.loads(row["policy_json"])
            role_key = "implementation" if role == "initial_engineering" else role
            limit = policy["roles"].get(role_key)
            if row["kind"] == "maintenance" and role != "maintenance" or published and role in {"implementation", "initial_engineering"}:
                fail("PUBLISHED_CASE_ROLE_FORBIDDEN", "Published maintenance cannot invoke the initial implementation role")
            if row["kind"] == "initial" and role == "maintenance":
                fail("TASK_ROLE_INVALID", "Maintenance requires its own published-context task")
            if not limit or policy["route_sha256"] != route_sha256 or output_limit > limit["output_limit"]:
                fail("TASK_POLICY_MISMATCH", "Model connection, role or output limit changed after task policy capture")
            units = request_bytes + output_limit
            identity = request_id or str(uuid.uuid4())
            previous = db.execute(text("SELECT * FROM agent_task_requests WHERE request_id=:id"), {"id": identity}).mappings().first()
            if previous:
                if (previous["task_id"], previous["role"], previous["request_sha256"], previous["reserved_units"]) != (self.task_id, role, request_sha256, units):
                    fail("MODEL_REQUEST_ID_CONFLICT", "Request operation identity changed")
                return identity, min(remaining, limit["timeout_seconds"])
            if row["reserved_units"] + units > policy["reservation_units"]:
                fail("TASK_RUN_LIMIT_REACHED", "达到任务运行上限；请求预留量超过服务端任务设置（不是已计费token）")
            db.execute(text("UPDATE agent_task_runs SET request_count=request_count+1,reserved_units=reserved_units+:units WHERE task_id=:id"), {"id": self.task_id, "units": units})
            if row["kind"] == "initial":
                db.execute(text("UPDATE agent_import_cases SET model_tokens_reserved=model_tokens_reserved+:units WHERE case_id=:id"), {"id": self.task_id, "units": units})
            db.execute(text("INSERT INTO agent_task_requests VALUES(:id,:task,:role,:units,:sha,'PREPARED',:now,NULL)"),
                {"id": identity, "task": self.task_id, "role": role, "units": units, "sha": request_sha256, "now": time.time()})
            return identity, min(remaining, limit["timeout_seconds"])

    def mark_sending(self, request_id):
        with self.engine.begin() as db:
            self._check(db, self._lock(db))
            result = db.execute(text("UPDATE agent_task_requests SET outcome='POSSIBLY_SENT' WHERE request_id=:id AND task_id=:task AND outcome='PREPARED'"), {"id": request_id, "task": self.task_id})
            if result.rowcount != 1:
                fail("MODEL_REQUEST_ALREADY_DISPATCHED", "A request cannot be sent twice")

    def finish(self, request_id, *, response, result):
        """Retain unknown sends; compensate only a provably unsent preparation."""
        accepted = True
        with self.engine.begin() as db:
            row = self._lock(db)
            req = db.execute(text("SELECT * FROM agent_task_requests WHERE request_id=:id AND task_id=:task"), {"id": request_id, "task": self.task_id}).mappings().one()
            if req["outcome"] not in {"PREPARED", "POSSIBLY_SENT"}:
                fail("MODEL_RESULT_CONFLICT", "A settled request is immutable")
            if req["outcome"] == "PREPARED" and response:
                fail("MODEL_RESULT_CONFLICT", "An unsent preparation cannot have a model response")
            if req["outcome"] == "PREPARED" and not response:
                outcome = "NOT_SENT"
                db.execute(text("UPDATE agent_task_runs SET request_count=request_count-1,reserved_units=reserved_units-:units WHERE task_id=:id"), {"id": self.task_id, "units": req["reserved_units"]})
                if row["kind"] == "initial":
                    db.execute(text("UPDATE agent_import_cases SET model_tokens_reserved=model_tokens_reserved-:units WHERE case_id=:id"), {"id": self.task_id, "units": req["reserved_units"]})
            else:
                outcome = "RESPONSE" if response else "UNKNOWN"
                if response:
                    try:
                        self._check(db, row)
                    except AgentImportError:
                        accepted, outcome = False, "LATE_RESULT_REJECTED"
            db.execute(text("UPDATE agent_task_requests SET outcome=:outcome,result_json=:result WHERE request_id=:id"), {"id": request_id, "outcome": outcome, "result": canonical(result)})
        return accepted

    def charge_preview(self, size):
        if size < 0:
            raise ValueError("Preview count cannot decrease")
        with self.engine.begin() as db:
            row = self._lock(db)
            self._check(db, row)
            if row["preview_used"] + size > json.loads(row["policy_json"])["preview_bytes"]:
                fail("MODEL_CONTEXT_BUDGET_EXCEEDED", "Cumulative task preview limit reached")
            db.execute(text("UPDATE agent_task_runs SET preview_used=preview_used+:size WHERE task_id=:id"), {"id": self.task_id, "size": size})

    def end(self):
        with self.engine.begin() as db:
            db.execute(text("UPDATE agent_task_runs SET ended_at=COALESCE(ended_at,:now) WHERE task_id=:id"), {"id": self.task_id, "now": time.time()})


_TASK = ContextVar("ordinary_model_task", default=None)


def current_task():
    return _TASK.get()


@contextmanager
def task_scope(runtime):
    token = _TASK.set(runtime)
    try:
        yield
    finally:
        _TASK.reset(token)


@contextmanager
def case_runtime_scope(service, case_id):
    runtime = TaskRuntime(service.engine, case_id)
    if runtime.exists():
        with task_scope(runtime):
            yield
    else:
        # Explicit old experiment compatibility only; never register/bind here.
        from .authorization_ledger import case_authority_scope
        with case_authority_scope(service, case_id):
            yield
