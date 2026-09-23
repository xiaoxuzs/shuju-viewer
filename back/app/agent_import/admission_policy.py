"""Server-owned finite import policies; bind before making a Case schedulable.

Policies reference grants in the SAME control database. No HTTP caller can mint
a grant or supply another owner's authorization/parent. Installation is a trusted
startup operation; all per-Case association is a domain-service transaction.
"""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .authorization_ledger import AuthorizationLedger, canonical, route_identity, utc
from .errors import AgentImportError

DDL = (
    """CREATE TABLE IF NOT EXISTS agent_import_policies (
        policy_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL REFERENCES agent_authorizations(authorization_id),
        owner_id TEXT NOT NULL, workspace_id TEXT NOT NULL, policy_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, installed_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_submission_keys (
        submission_key TEXT PRIMARY KEY, case_id TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS agent_stage_budgets (
        lineage_id TEXT NOT NULL, role TEXT NOT NULL, calls_used INTEGER NOT NULL DEFAULT 0,
        reserved_units BIGINT NOT NULL DEFAULT 0, started_at DOUBLE PRECISION NOT NULL,
        elapsed_seconds DOUBLE PRECISION NOT NULL DEFAULT 0, PRIMARY KEY(lineage_id,role))""",
)


class StageLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calls: int = Field(ge=1, le=1000)
    units: int = Field(ge=1)
    seconds: int = Field(ge=1, le=14400)


class ImportPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str = Field(min_length=1, max_length=100)
    authorization_id: str = Field(min_length=1, max_length=100)
    owner_id: str = Field(min_length=1, max_length=100)
    workspace_id: str = Field(default="default", min_length=1, max_length=100)
    environment: str = Field(pattern="^(test|development)$")
    source_root: str
    purpose: str = Field(default="initial_import", pattern="^(initial_import|maintenance)$")
    valid_until: float
    experiment_seconds: int = Field(ge=1, le=3600)
    case_calls: int = Field(ge=1, le=1000)
    case_units: int = Field(ge=1)
    preview_bytes: int = Field(default=131072, ge=1, le=131072)
    stages: dict[str, StageLimit]


def install_policy(engine, policy: ImportPolicy):
    """Never called by a public creation endpoint. Does not grant new budget."""
    from .model_routing import route_for
    route = route_for("research")
    ledger = AuthorizationLedger(engine)
    root = Path(policy.source_root).absolute()
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("Policy source root must be an existing nonlinked directory")
    if policy.environment != os.environ.get("VIEWER_ENV") or policy.valid_until <= time.time():
        raise ValueError("Policy environment/expiry does not match the explicit runtime")
    if not {"research", "implementation", "review"}.issubset(policy.stages) and policy.purpose == "initial_import":
        raise ValueError("Finite research/implementation/review stage limits are required")
    if policy.purpose == "maintenance" and set(policy.stages) != {"maintenance"}:
        raise ValueError("Published maintenance policy can authorize only the independent maintenance role")
    encoded = canonical(policy.model_dump(mode="json"))
    with engine.begin() as db:
        _, contract = ledger._lock(db, policy.authorization_id)
        if contract["route_sha256"] != route_identity(route.base_url + "/chat/completions", route.model):
            raise ValueError("Policy does not match the single configured model route")
        if policy.case_calls > contract["request_limit"] or policy.case_units > contract["reservation_limit"] or policy.experiment_seconds > contract["experiment_seconds"]:
            raise ValueError("Policy cannot enlarge its grant")
        if any(role not in contract["roles"] for role in policy.stages):
            raise ValueError("Policy contains an ungranted model role")
        prior = db.execute(text("SELECT policy_json FROM agent_import_policies WHERE policy_id=:id"), {"id": policy.policy_id}).scalar()
        if prior is not None:
            if prior != encoded:
                raise ValueError("Installed policy is immutable; budget must not reset on restart")
            return
        db.execute(text("INSERT INTO agent_import_policies VALUES (:id,:grant,:owner,:workspace,:policy,1,:now)"),
            {"id": policy.policy_id, "grant": policy.authorization_id, "owner": policy.owner_id,
             "workspace": policy.workspace_id, "policy": encoded, "now": utc()})
        ledger._event(db, policy.authorization_id, "IMPORT_POLICY_INSTALLED", {"policy_id": policy.policy_id})


def submission_identity(owner, workspace, source_identity, category, profile, details):
    return hashlib.sha256(canonical([owner, workspace, source_identity, category, profile, details]).encode()).hexdigest()


def bind_pending_tx(db, engine, case):
    """Caller owns the Case transaction. No network, separate transaction or grant creation."""
    from .model_routing import route_for
    now = time.time()
    ledger = AuthorizationLedger(engine)
    existing = db.execute(text("SELECT * FROM agent_case_authority WHERE case_id=:id"), {"id": case["case_id"]}).mappings().first()
    if existing:
        # Never silently reset an expired already-running experiment.
        try:
            grant, contract, line, _ = ledger._check(db, existing["authorization_id"], existing["experiment_id"], existing["lineage_id"])
        except AgentImportError as exc:
            return exc.code
        if grant["calls_used"] >= contract["request_limit"] or grant["reserved_units"] >= contract["reservation_limit"] or line["calls_used"] >= line["call_limit"] or line["reserved_units"] >= line["unit_limit"]:
            return "AUTHORIZATION_EXHAUSTED"
        if case["authorization_wait_reason"] == "MODEL_STAGE_BUDGET_EXHAUSTED":
            return "MODEL_STAGE_BUDGET_EXHAUSTED"
        return None
    policies = db.execute(text("SELECT * FROM agent_import_policies WHERE owner_id=:owner AND workspace_id=:workspace AND enabled=1 ORDER BY installed_at,policy_id"),
        {"owner": case["owner_id"], "workspace": case["workspace_id"]}).mappings().all()
    reason = "NO_MATCHING_POLICY"
    published = db.execute(text("""SELECT case_id FROM agent_import_cases WHERE source_content_sha256=:source
        AND owner_id=:owner AND workspace_id=:workspace AND ever_published=1 LIMIT 1"""),
        {"source": case["source_content_sha256"], "owner": case["owner_id"], "workspace": case["workspace_id"]}).first()
    if published:
        return "PUBLISHED_SOURCE_REQUIRES_MAINTENANCE"
    route = route_for("research")
    for stored in policies:
        policy = ImportPolicy.model_validate_json(stored["policy_json"])
        if policy.purpose != "initial_import" or policy.environment != os.environ.get("VIEWER_ENV"):
            continue
        if not Path(case["source_ref"]).resolve().is_relative_to(Path(policy.source_root)):
            continue
        if now >= policy.valid_until:
            reason = "POLICY_EXPIRED"
            continue
        try:
            grant, contract = ledger._lock(db, policy.authorization_id)
        except AgentImportError as exc:
            reason = exc.code
            continue
        if contract["route_sha256"] != route_identity(route.base_url + "/chat/completions", route.model):
            reason = "MODEL_AUTHORIZATION_MISMATCH"
            continue
        remaining = contract["active_seconds"] - ledger._elapsed(db, policy.authorization_id, now)
        if remaining <= 0 or grant["calls_used"] >= contract["request_limit"] or grant["reserved_units"] >= contract["reservation_limit"]:
            reason = "AUTHORIZATION_EXHAUSTED"
            continue
        # Same source within this owner's workspace inherits the previous lineage.
        parent = db.execute(text("""SELECT l.* FROM agent_authorized_lineages l JOIN agent_import_cases c ON c.case_id=l.case_id
            WHERE l.authorization_id=:grant AND l.source_identity=:source AND c.owner_id=:owner AND c.workspace_id=:workspace
            ORDER BY c.created_at LIMIT 1"""), {"grant": policy.authorization_id, "source": case["source_content_sha256"], "owner": case["owner_id"], "workspace": case["workspace_id"]}).mappings().first()
        if parent and parent["published"]:
            return "PUBLISHED_SOURCE_REQUIRES_MAINTENANCE"
        if parent and (parent["calls_used"] >= parent["call_limit"] or parent["reserved_units"] >= parent["unit_limit"]):
            return "LINEAGE_BUDGET_EXHAUSTED"
        lineage, experiment = str(uuid.uuid4()), str(uuid.uuid4())
        end = min(now + policy.experiment_seconds, now + remaining, policy.valid_until)
        db.execute(text("INSERT INTO agent_experiments VALUES (:id,:grant,'initial_import',:now,:end,NULL,NULL)"),
                   {"id": experiment, "grant": policy.authorization_id, "now": now, "end": end})
        db.execute(text("""INSERT INTO agent_authorized_lineages
            (lineage_id,authorization_id,case_id,parent_lineage_id,published,call_limit,calls_used,unit_limit,reserved_units,preview_limit,source_identity)
            VALUES (:lineage,:grant,:case,:parent,0,:calls,0,:units,:reserved,:preview,:source)"""),
            {"lineage": lineage, "grant": policy.authorization_id, "case": case["case_id"], "parent": parent["lineage_id"] if parent else None,
             "calls": policy.case_calls, "units": policy.case_units, "reserved": case["model_tokens_reserved"],
             "preview": policy.preview_bytes, "source": case["source_content_sha256"]})
        db.execute(text("INSERT INTO agent_case_authority (case_id,authorization_id,experiment_id,lineage_id,policy_id) VALUES (:case,:grant,:experiment,:lineage,:policy)"),
            {"case": case["case_id"], "grant": policy.authorization_id, "experiment": experiment, "lineage": lineage, "policy": policy.policy_id})
        db.execute(text("UPDATE agent_import_cases SET deadline_at=:end,authorization_wait_reason=NULL WHERE case_id=:id"),
            {"id": case["case_id"], "end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
        ledger._event(db, policy.authorization_id, "CASE_AUTO_BOUND", {"case_id": case["case_id"], "lineage_id": lineage,
            "experiment_id": experiment, "policy_id": policy.policy_id, "parent_lineage_id": parent["lineage_id"] if parent else None})
        return None
    return reason


def wake_waiting(service):
    """Bounded consumer called by the existing Worker, not a second scheduler."""
    with service.engine.connect() as db:
        pending = db.execute(text("SELECT case_id,owner_id,workspace_id FROM agent_import_cases WHERE status='WAITING_AUTHORIZATION' AND stop_requested_at IS NULL ORDER BY created_at LIMIT 20")).mappings().all()
    for item in pending:
        _wake_one(service, item)


def _wake_one(service, item):
    with service.engine.begin() as db:
        # Same lock order as model reservation: grant(s), then Case. Never hold
        # a Case row while waiting on a grant locked by an in-flight request.
        grants = db.execute(text("""SELECT authorization_id FROM agent_import_policies WHERE owner_id=:owner AND workspace_id=:workspace
            UNION SELECT authorization_id FROM agent_case_authority WHERE case_id=:id ORDER BY authorization_id"""),
            {"id": item["case_id"], "owner": item["owner_id"], "workspace": item["workspace_id"]}).scalars().all()
        for grant in grants:
            db.execute(text("UPDATE agent_authorizations SET serial=serial+1 WHERE authorization_id=:id"), {"id": grant})
        lock = " FOR UPDATE SKIP LOCKED" if db.dialect.name == "postgresql" else ""
        case = db.execute(text("SELECT * FROM agent_import_cases WHERE case_id=:id AND status='WAITING_AUTHORIZATION' AND stop_requested_at IS NULL" + lock), {"id": item["case_id"]}).mappings().first()
        if case:
            reason = bind_pending_tx(db, service.engine, case)
            if reason is not None and reason == case["authorization_wait_reason"]:
                return
            db.execute(text("UPDATE agent_import_cases SET status=:state,authorization_wait_reason=:reason,version=version+1 WHERE case_id=:id AND status='WAITING_AUTHORIZATION'"),
                       {"id": case["case_id"], "state": (case["authorization_resume_status"] or "CREATED") if reason is None else "WAITING_AUTHORIZATION", "reason": reason})
