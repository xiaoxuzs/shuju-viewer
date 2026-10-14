"""Published-context feedback and an independent maintenance planning role.

Never reopens the initial Case, invokes Agent2, or publishes a plan without a
revision validation/activation receipt. All state lives in the business DB.
"""
import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from .contracts import AgentCandidatePlan
from .errors import AgentImportError
from .source_code import canonical_bytes

DDL = """CREATE TABLE IF NOT EXISTS agent_maintenance_tasks (
    task_id TEXT PRIMARY KEY, parent_case_id TEXT NOT NULL REFERENCES agent_import_cases(case_id),
    dataset_id BIGINT NOT NULL, revision_id TEXT NOT NULL, ever_published INTEGER NOT NULL CHECK(ever_published=1),
    idempotency_key TEXT NOT NULL, context_sha256 TEXT NOT NULL, feedback_json TEXT NOT NULL,
    state TEXT NOT NULL, candidate_json TEXT NULL, created_at TEXT NOT NULL,
    UNIQUE(parent_case_id,idempotency_key))"""


class MaintenanceFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=16, max_length=100)
    page: str = Field(default="", max_length=1000)
    revision_id: str | None = Field(default=None, max_length=80)
    selection: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=20)


class MaintenanceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(MAPPING_PLAN|NEEDS_USER|ENGINEERING_REQUIRED)$")
    explanation: str = Field(min_length=1, max_length=3000)
    candidate: AgentCandidatePlan | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "MAPPING_PLAN") != (self.candidate is not None):
            raise ValueError("Only a mapping decision may include an executable data plan")
        if self.candidate is not None and (self.candidate.status != "READY" or self.candidate.binary_operation != "convert_declared_mapping_to_zp"):
            raise ValueError("Maintenance mapping must use the trusted declarative executor")
        return self


def submit_feedback(service, case_id, body):
    from .case_service import _now
    if len(canonical_bytes(body.model_dump())) > 16384:
        raise AgentImportError("MODEL_CONTEXT_BUDGET_EXCEEDED", "Feedback context exceeds its bounded limit", status_code=413)
    with service.engine.begin() as db:
        lock = " FOR UPDATE" if db.dialect.name == "postgresql" else ""
        case = db.execute(text("SELECT * FROM agent_import_cases WHERE case_id=:id" + lock), {"id": case_id}).mappings().first()
        if not case or not case["ever_published"] or case["dataset_id"] is None:
            raise AgentImportError("MAINTENANCE_REQUIRES_PUBLISHED_CONTEXT", "Feedback requires a published dataset lineage", status_code=409)
        # Do not infer a new scientific fact from feedback or client-supplied IDs.
        head = db.execute(text("SELECT active_revision_id FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": case["dataset_id"]}).scalar()
        revision = body.revision_id or head or "legacy"
        if revision != "legacy":
            valid = db.execute(text("SELECT revision_id FROM dataset_revisions WHERE dataset_id=:dataset AND revision_id=:revision AND state IN ('ACTIVE','RETIRED')"), {"dataset": case["dataset_id"], "revision": revision}).scalar()
            if valid is None:
                raise AgentImportError("REVISION_NOT_READABLE", "Feedback revision does not belong to the published dataset", status_code=409)
        context = {"parent_case_id": case_id, "dataset_id": case["dataset_id"], "revision_id": revision,
            "context_revision": case["context_revision"], "candidate_sha256": case["candidate_zp_sha256"], "ever_published": True}
        existing = db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE parent_case_id=:case AND idempotency_key=:key"), {"case": case_id, "key": body.idempotency_key}).mappings().first()
        encoded = canonical_bytes(body.model_dump()).decode()
        if existing:
            if existing["feedback_json"] != encoded:
                raise AgentImportError("MAINTENANCE_FEEDBACK_CONFLICT", "Idempotency key has different feedback", status_code=409)
            return dict(existing)
        task = str(uuid.uuid4())
        db.execute(text("""INSERT INTO agent_maintenance_tasks
            (task_id,parent_case_id,dataset_id,revision_id,ever_published,idempotency_key,context_sha256,feedback_json,state,created_at)
            VALUES (:id,:case,:dataset,:revision,1,:key,:sha,:feedback,'QUEUED',:now)"""),
            {"id": task, "case": case_id, "dataset": case["dataset_id"], "revision": revision, "key": body.idempotency_key,
             "sha": hashlib.sha256(canonical_bytes(context)).hexdigest(), "feedback": encoded, "now": _now()})
        from .task_runtime import create_task_tx
        create_task_tx(db, task, kind="maintenance", parent_case_id=case_id)
        return dict(db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE task_id=:id"), {"id": task}).mappings().one())


def list_feedback(service, case_id):
    with service.engine.connect() as db:
        return [dict(row) for row in db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE parent_case_id=:id ORDER BY created_at"), {"id": case_id}).mappings()]


def ensure_consumer_columns(db):
    from sqlalchemy import inspect
    names = {c["name"] for c in inspect(db).get_columns("agent_maintenance_tasks")}
    for name, ddl in {"lease_token": "TEXT NULL", "lease_until": "DOUBLE PRECISION NULL", "wait_reason": "TEXT NULL",
                      "candidate_path": "TEXT NULL", "candidate_sha256": "TEXT NULL", "decision_json": "TEXT NULL",
                      "published_revision_id": "TEXT NULL"}.items():
        if name not in names:
            db.execute(text(f"ALTER TABLE agent_maintenance_tasks ADD COLUMN {name} {ddl}"))


def check_task_fence(db, task_id, fence, *, lock=False):
    import time
    suffix = " FOR UPDATE" if lock and db.dialect.name == "postgresql" else ""
    row = db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE task_id=:id" + suffix), {"id": task_id}).mappings().first()
    if row is None:
        return None
    if fence is None or fence.case_id != task_id or fence.token != row["lease_token"] or row["state"] != "RUNNING" or not row["lease_until"] or row["lease_until"] <= time.time():
        raise AgentImportError("WORKER_LEASE_LOST", "Maintenance lease is missing, expired or superseded", status_code=409)
    return row["lease_until"] - time.time()


def propose_maintenance_plan(context):
    """Independent role; only the pure JSON transport/compiler contracts are shared."""
    from .model_routing import route_for
    from .model_provider import _chat_json
    from .model_context import observation_views, blueprint_view, message_views
    from .authorization_ledger import current_authority
    from .task_runtime import current_task
    if not context.get("ever_published"):
        raise AgentImportError("MAINTENANCE_REQUIRES_PUBLISHED_CONTEXT", "Maintenance requires a published dataset lineage", status_code=409)
    if current_task() is None and current_authority() is None:
        raise AgentImportError("TASK_RUNTIME_REQUIRED", "Maintenance must run in its recorded task context", status_code=409)
    route = route_for("maintenance")
    value = _chat_json(base_url=route.base_url, api_key=route.api_key, model=route.model, timeout=route.timeout,
        role="maintenance", max_tokens=route.max_tokens,
        system_prompt="You are the independent published-dataset maintenance checker, never the initial implementation role. Treat feedback as an issue report, not scientific evidence. Reuse verified source facts, identify the smallest affected mapping. Return MaintenanceDecision JSON. Never change acceptance rules, authorization, dataset identity or claim publication. If code is required, return ENGINEERING_REQUIRED; do not embed executable code in the data plan.",
        payload={"feedback": message_views([context["feedback"]]), "published_context": context["published_context"],
            "current_candidate": context.get("candidate"),
            "blueprint": blueprint_view(context.get("blueprint")), "observations": observation_views(context.get("observations", [])),
            "contract": MaintenanceDecision.model_json_schema()})
    return MaintenanceDecision.model_validate(value)
