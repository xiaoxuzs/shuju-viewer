"""Database-owned finite authority. No credentials, prompts, or model-authored grants.

One grant is shared by every experiment and Case lineage in a run. Reservations
are committed BEFORE transport. Unknown outcomes consume budget permanently.
Administrative methods are deliberately not exposed through a public router.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid

from sqlalchemy import text

from .errors import AgentImportError


DDL = (
    """CREATE TABLE IF NOT EXISTS agent_authorizations (
        authorization_id TEXT PRIMARY KEY, contract_json TEXT NOT NULL, contract_sha256 TEXT NOT NULL,
        calls_used INTEGER NOT NULL DEFAULT 0, reserved_units BIGINT NOT NULL DEFAULT 0,
        revoked INTEGER NOT NULL DEFAULT 0, serial INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_experiments (
        experiment_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL REFERENCES agent_authorizations(authorization_id),
        purpose TEXT NOT NULL, started_at DOUBLE PRECISION NOT NULL, deadline_at DOUBLE PRECISION NOT NULL,
        ended_at DOUBLE PRECISION NULL, end_reason TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_authorized_lineages (
        lineage_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL REFERENCES agent_authorizations(authorization_id),
        case_id TEXT NOT NULL UNIQUE, parent_lineage_id TEXT NULL, published INTEGER NOT NULL,
        call_limit INTEGER NOT NULL, calls_used INTEGER NOT NULL, unit_limit BIGINT NOT NULL,
        reserved_units BIGINT NOT NULL, preview_limit BIGINT NOT NULL, preview_used BIGINT NOT NULL DEFAULT 0,
        recovery_activated INTEGER NOT NULL DEFAULT 0, source_identity TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_request_reservations (
        request_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL REFERENCES agent_authorizations(authorization_id),
        experiment_id TEXT NOT NULL REFERENCES agent_experiments(experiment_id),
        lineage_id TEXT NOT NULL REFERENCES agent_authorized_lineages(lineage_id),
        role TEXT NOT NULL, reserved_units BIGINT NOT NULL, request_sha256 TEXT NOT NULL,
        reserved_at TEXT NOT NULL, outcome TEXT NOT NULL, result_json TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_authorization_events (
        event_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL, kind TEXT NOT NULL,
        created_at TEXT NOT NULL, payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_case_authority (
        case_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL, experiment_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL, binding_version INTEGER NOT NULL DEFAULT 1)""",
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def utc():
    return datetime.now(timezone.utc).isoformat()


def reject(code, message):
    raise AgentImportError(code, message, status_code=409)


def interval_union(intervals):
    end = None
    total = 0.0
    for start, stop in sorted(intervals):
        if stop < start:
            raise ValueError("Clock moved before recorded experiment start")
        total += max(0.0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return total


class AuthorizationLedger:
    def __init__(self, engine, *, clock=time.time):
        self.engine, self.clock = engine, clock

    def ensure_schema(self):
        with self.engine.begin() as db:
            for statement in DDL:
                db.execute(text(statement))

    def _event(self, db, grant, kind, payload):
        db.execute(text("INSERT INTO agent_authorization_events VALUES (:id,:grant,:kind,:now,:payload)"),
                   {"id": str(uuid.uuid4()), "grant": grant, "kind": kind, "now": utc(), "payload": canonical(payload)})

    def register(self, grant, contract):
        required = {"request_limit", "reservation_limit", "active_seconds", "experiment_seconds", "output_limit", "route_sha256", "roles", "authorization_basis"}
        if set(contract) != required or any(type(contract[k]) is not int or contract[k] <= 0 for k in required - {"route_sha256", "roles", "authorization_basis"}):
            raise ValueError("An explicit finite authorization contract is required")
        if not contract["authorization_basis"] or not contract["roles"] or len(contract["route_sha256"]) != 64:
            raise ValueError("Authorization identity is missing")
        value = canonical(contract)
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self.engine.begin() as db:
            prior = db.execute(text("SELECT contract_sha256 FROM agent_authorizations WHERE authorization_id=:id"), {"id": grant}).scalar()
            if prior:
                if prior != digest:
                    reject("AUTHORIZATION_IMMUTABLE", "A registered grant cannot be enlarged or replaced")
                return
            db.execute(text("INSERT INTO agent_authorizations (authorization_id,contract_json,contract_sha256,created_at) VALUES (:id,:value,:sha,:now)"),
                       {"id": grant, "value": value, "sha": digest, "now": utc()})
            self._event(db, grant, "AUTHORIZED", {"contract_sha256": digest})

    def _lock(self, db, grant):
        # UPDATE obtains a write lock also on SQLite, before any budget read.
        result = db.execute(text("UPDATE agent_authorizations SET serial=serial+1 WHERE authorization_id=:id"), {"id": grant})
        if result.rowcount != 1:
            reject("MODEL_AUTHORIZATION_REQUIRED", "No registered model authorization")
        row = db.execute(text("SELECT * FROM agent_authorizations WHERE authorization_id=:id"), {"id": grant}).mappings().one()
        if row["revoked"]:
            reject("AUTHORIZATION_REVOKED", "Authorization has been revoked")
        return row, json.loads(row["contract_json"])

    def _elapsed(self, db, grant, now):
        rows = db.execute(text("SELECT started_at,deadline_at,ended_at FROM agent_experiments WHERE authorization_id=:id"), {"id": grant})
        # An unreconciled crash is NOT proof that every parser/child stopped.
        # Charge through now, even past deadline, until the trusted controller
        # confirms termination. The deadline blocks work; it is not a fake pause.
        return interval_union([(r.started_at, r.ended_at if r.ended_at is not None else now) for r in rows])

    def begin_experiment(self, grant, purpose, seconds, *, experiment_id=None):
        now = self.clock()
        with self.engine.begin() as db:
            _, contract = self._lock(db, grant)
            remaining = contract["active_seconds"] - self._elapsed(db, grant, now)
            if seconds <= 0 or seconds > contract["experiment_seconds"] or remaining <= 0:
                reject("EXPERIMENT_BUDGET_EXCEEDED", "Finite experiment window unavailable")
            identity = experiment_id or str(uuid.uuid4())
            db.execute(text("INSERT INTO agent_experiments VALUES (:id,:grant,:purpose,:now,:deadline,NULL,NULL)"),
                       {"id": identity, "grant": grant, "purpose": purpose, "now": now, "deadline": now + min(seconds, remaining)})
            self._event(db, grant, "EXPERIMENT_STARTED", {"experiment_id": identity, "start_utc_epoch": now, "seconds": min(seconds, remaining)})
            return identity

    def end_experiment(self, grant, experiment, reason):
        with self.engine.begin() as db:
            # Revocation stops work, not cleanup accounting.
            db.execute(text("UPDATE agent_authorizations SET serial=serial+1 WHERE authorization_id=:id"), {"id": grant})
            row = db.execute(text("SELECT * FROM agent_experiments WHERE experiment_id=:id AND authorization_id=:grant"), {"id": experiment, "grant": grant}).mappings().one()
            if row["ended_at"] is None:
                now = self.clock()
                if now < row["started_at"]:
                    reject("AUTHORIZATION_CLOCK_INVALID", "Experiment clock moved backwards")
                db.execute(text("UPDATE agent_experiments SET ended_at=:now,end_reason=:reason WHERE experiment_id=:id"), {"id": experiment, "now": now, "reason": reason})
                self._event(db, grant, "EXPERIMENT_ENDED", {"experiment_id": experiment, "end_utc_epoch": now, "reason": reason})

    def bind_case(self, grant, case_id, source_identity, *, call_limit, unit_limit, historical_calls=0, historical_reserved=0, published=False, parent=None, preview_limit=131072):
        """Trusted controller only; no client-supplied lineage or history."""
        if historical_calls < 0 or historical_reserved < 0 or call_limit < historical_calls or unit_limit < historical_reserved:
            raise ValueError("Historical consumption cannot be erased")
        with self.engine.begin() as db:
            self._lock(db, grant)
            existing = db.execute(text("SELECT * FROM agent_authorized_lineages WHERE case_id=:case"), {"case": case_id}).mappings().first()
            if existing:
                if existing["authorization_id"] != grant or existing["source_identity"] != source_identity:
                    reject("LINEAGE_AUTHORIZATION_CONFLICT", "Case authority cannot be silently rebound")
                return existing["lineage_id"]
            if parent:
                ancestor = db.execute(text("SELECT * FROM agent_authorized_lineages WHERE lineage_id=:id AND authorization_id=:grant"), {"id": parent, "grant": grant}).mappings().one()
                published = published or bool(ancestor["published"])
            lineage = str(uuid.uuid4())
            db.execute(text("""INSERT INTO agent_authorized_lineages
                (lineage_id,authorization_id,case_id,parent_lineage_id,published,call_limit,calls_used,unit_limit,reserved_units,preview_limit,source_identity)
                VALUES (:id,:grant,:case,:parent,:published,:calls,:used,:units,:reserved,:preview,:source)"""),
                {"id": lineage, "grant": grant, "case": case_id, "parent": parent, "published": int(published), "calls": call_limit,
                 "used": historical_calls, "units": unit_limit, "reserved": historical_reserved, "preview": preview_limit, "source": source_identity})
            self._event(db, grant, "LINEAGE_BOUND", {"lineage_id": lineage, "case_id": case_id, "parent": parent, "historical_calls": historical_calls, "historical_reserved": historical_reserved})
            return lineage

    def _check(self, db, grant, experiment, lineage):
        row, contract = self._lock(db, grant)
        now = self.clock()
        exp = db.execute(text("SELECT * FROM agent_experiments WHERE experiment_id=:id AND authorization_id=:grant"), {"id": experiment, "grant": grant}).mappings().first()
        line = db.execute(text("SELECT * FROM agent_authorized_lineages WHERE lineage_id=:id AND authorization_id=:grant"), {"id": lineage, "grant": grant}).mappings().first()
        if not exp or not line or exp["ended_at"] is not None:
            reject("MODEL_AUTHORIZATION_REQUIRED", "An active experiment and server-owned lineage are required")
        remaining = min(exp["deadline_at"] - now, contract["active_seconds"] - self._elapsed(db, grant, now))
        if now < exp["started_at"] or remaining <= 0:
            reject("EXPERIMENT_BUDGET_EXCEEDED", "Experiment deadline or cumulative activity budget exhausted")
        return row, contract, line, remaining

    def check(self, grant, experiment, lineage):
        with self.engine.begin() as db:
            return self._check(db, grant, experiment, lineage)[3]

    def reserve(self, grant, experiment, lineage, *, role, route_sha256, request_bytes, output_limit, request_sha256, request_id=None):
        units = request_bytes + output_limit
        if request_bytes < 0 or output_limit <= 0:
            raise ValueError("Invalid request reservation")
        with self.engine.begin() as db:
            row, contract, line, remaining = self._check(db, grant, experiment, lineage)
            request_id = request_id or str(uuid.uuid4())
            previous = db.execute(text("SELECT * FROM agent_request_reservations WHERE request_id=:id"), {"id": request_id}).mappings().first()
            if previous:
                if (previous["authorization_id"], previous["experiment_id"], previous["lineage_id"], previous["role"], previous["request_sha256"], previous["reserved_units"]) != (grant, experiment, lineage, role, request_sha256, units):
                    reject("MODEL_REQUEST_ID_CONFLICT", "Request operation identity changed")
                return request_id, remaining
            # One short transaction covers both the authorization and Case counters.
            from .execution_control import current_fence
            from sqlalchemy import inspect
            case = None
            if inspect(db).has_table("agent_import_cases"):
                lock = " FOR UPDATE" if db.dialect.name == "postgresql" else ""
                case = db.execute(text("SELECT * FROM agent_import_cases WHERE case_id=:id" + lock), {"id": line["case_id"]}).mappings().first()
            if case is not None:
                fence = current_fence()
                if fence is None or fence.case_id != case["case_id"] or fence.token != case["lease_token"] or not case["lease_owner"] or not case["lease_expires_at"] or datetime.fromisoformat(case["lease_expires_at"]) <= datetime.now(timezone.utc):
                    reject("WORKER_LEASE_LOST", "No current Worker fence for the request")
                if case["stop_requested_at"] or case["status"] in {"STOPPING", "STOPPED", "FAILED", "SUCCESS"}:
                    reject("AGENT_CANCELLED", "Case no longer permits this request")
                remaining = min(remaining, (datetime.fromisoformat(case["deadline_at"]) - datetime.now(timezone.utc)).total_seconds())
                if remaining <= 0:
                    reject("AGENT_DEADLINE_EXCEEDED", "Case deadline expired before reservation")
            elif inspect(db).has_table("agent_maintenance_tasks"):
                from .maintenance import check_task_fence
                task_remaining = check_task_fence(db, line["case_id"], current_fence())
                if task_remaining is not None:
                    remaining = min(remaining, task_remaining)
            policy = None
            if inspect(db).has_table("agent_import_policies"):
                raw_policy = db.execute(text("""SELECT p.policy_json FROM agent_import_policies p JOIN agent_case_authority a ON a.policy_id=p.policy_id
                    WHERE a.lineage_id=:id"""), {"id": lineage}).scalar()
                policy = json.loads(raw_policy) if raw_policy else None
            if policy:
                limit = policy["stages"].get(role)
                if not limit:
                    reject("MODEL_AUTHORIZATION_MISMATCH", "Role has no granted stage budget")
                stage = db.execute(text("SELECT * FROM agent_stage_budgets WHERE lineage_id=:id AND role=:role"), {"id": lineage, "role": role}).mappings().first()
                if stage is None:
                    db.execute(text("INSERT INTO agent_stage_budgets (lineage_id,role,started_at) VALUES (:id,:role,:now)"), {"id": lineage, "role": role, "now": self.clock()})
                    stage = {"calls_used": 0, "reserved_units": 0, "started_at": self.clock()}
                remaining = min(remaining, stage["started_at"] + limit["seconds"] - self.clock())
                if remaining <= 0 or stage["calls_used"] >= limit["calls"] or stage["reserved_units"] + units > limit["units"]:
                    reject("MODEL_STAGE_BUDGET_EXHAUSTED", "Frozen stage budget exhausted")
            ancestors = [line]
            while ancestors[-1]["parent_lineage_id"]:
                parent = ancestors[-1]["parent_lineage_id"]
                if parent in {a["lineage_id"] for a in ancestors}:
                    reject("LINEAGE_AUTHORIZATION_CONFLICT", "Cyclic lineage")
                ancestors.append(db.execute(text("SELECT * FROM agent_authorized_lineages WHERE lineage_id=:id AND authorization_id=:grant"), {"id": parent, "grant": grant}).mappings().one())
            if role not in contract["roles"] or route_sha256 != contract["route_sha256"] or output_limit > contract["output_limit"]:
                reject("MODEL_AUTHORIZATION_MISMATCH", "Model route, role or output limit differs from granted authority")
            if any(a["published"] for a in ancestors) and role in {"implementation", "initial_engineering"}:
                reject("PUBLISHED_CASE_ROLE_FORBIDDEN", "Published lineage cannot call the initial implementation role")
            if row["calls_used"] >= contract["request_limit"] or row["reserved_units"] + units > contract["reservation_limit"] or any(a["calls_used"] >= a["call_limit"] or a["reserved_units"] + units > a["unit_limit"] for a in ancestors):
                reject("MODEL_AUTHORIZATION_EXHAUSTED", "Cumulative grant or lineage request budget exhausted")
            db.execute(text("UPDATE agent_authorizations SET calls_used=calls_used+1,reserved_units=reserved_units+:units WHERE authorization_id=:id"), {"id": grant, "units": units})
            for ancestor in ancestors:
                db.execute(text("UPDATE agent_authorized_lineages SET calls_used=calls_used+1,reserved_units=reserved_units+:units WHERE lineage_id=:id"), {"id": ancestor["lineage_id"], "units": units})
            if case is not None:
                db.execute(text("UPDATE agent_import_cases SET model_tokens_reserved=model_tokens_reserved+:units WHERE case_id=:id"), {"id": case["case_id"], "units": units})
            if policy:
                db.execute(text("UPDATE agent_stage_budgets SET calls_used=calls_used+1,reserved_units=reserved_units+:units WHERE lineage_id=:id AND role=:role"), {"id": lineage, "role": role, "units": units})
            db.execute(text("INSERT INTO agent_request_reservations VALUES (:id,:grant,:experiment,:lineage,:role,:units,:sha,:now,'PREPARED',NULL)"),
                       {"id": request_id, "grant": grant, "experiment": experiment, "lineage": lineage, "role": role, "units": units, "sha": request_sha256, "now": utc()})
            return request_id, remaining

    def mark_sending(self, request_id):
        with self.engine.begin() as db:
            request = db.execute(text("SELECT * FROM agent_request_reservations WHERE request_id=:id"), {"id": request_id}).mappings().one()
            self._check(db, request["authorization_id"], request["experiment_id"], request["lineage_id"])
            from .execution_control import current_fence
            from sqlalchemy import inspect
            fence = current_fence()
            case = None
            if inspect(db).has_table("agent_import_cases"):
                case = db.execute(text("""SELECT c.* FROM agent_import_cases c JOIN agent_authorized_lineages l ON l.case_id=c.case_id
                    WHERE l.lineage_id=:id"""), {"id": request["lineage_id"]}).mappings().first()
            if case is not None:
                if fence is None or fence.case_id != case["case_id"] or case["lease_token"] != fence.token or not case["lease_expires_at"] or datetime.fromisoformat(case["lease_expires_at"]) <= datetime.now(timezone.utc) or case["stop_requested_at"] or case["status"] in {"FAILED", "STOPPED", "SUCCESS", "WAITING_AUTHORIZATION"}:
                    reject("WORKER_LEASE_LOST", "Case cancelled or lease lost before dispatch")
            elif inspect(db).has_table("agent_maintenance_tasks"):
                from .maintenance import check_task_fence
                task_id = db.execute(text("SELECT case_id FROM agent_authorized_lineages WHERE lineage_id=:id"), {"id": request["lineage_id"]}).scalar_one()
                check_task_fence(db, task_id, fence)
            changed = db.execute(text("UPDATE agent_request_reservations SET outcome='POSSIBLY_SENT' WHERE request_id=:id AND outcome='PREPARED'"), {"id": request_id})
            if changed.rowcount != 1:
                reject("MODEL_REQUEST_ALREADY_DISPATCHED", "This reservation cannot cause another HTTP send")

    def release_unsent(self, request_id, reason):
        """Trusted transport/controller only. PREPARED is proof no send was authorized."""
        with self.engine.begin() as db:
            db.execute(text("UPDATE agent_authorizations SET serial=serial+1 WHERE authorization_id=(SELECT authorization_id FROM agent_request_reservations WHERE request_id=:id)"), {"id": request_id})
            req = db.execute(text("SELECT * FROM agent_request_reservations WHERE request_id=:id"), {"id": request_id}).mappings().one()
            if req["outcome"] == "NOT_SENT":
                return
            if req["outcome"] != "PREPARED":
                reject("MODEL_RECONCILIATION_REQUIRED", "Possibly sent requests must remain consumed")
            db.execute(text("UPDATE agent_request_reservations SET outcome='NOT_SENT',result_json=:result WHERE request_id=:id"), {"id": request_id, "result": canonical({"reason": reason})})
            db.execute(text("UPDATE agent_authorizations SET calls_used=calls_used-1,reserved_units=reserved_units-:units WHERE authorization_id=:id"), {"id": req["authorization_id"], "units": req["reserved_units"]})
            node = req["lineage_id"]
            while node:
                line = db.execute(text("SELECT * FROM agent_authorized_lineages WHERE lineage_id=:id"), {"id": node}).mappings().one()
                db.execute(text("UPDATE agent_authorized_lineages SET calls_used=calls_used-1,reserved_units=reserved_units-:units WHERE lineage_id=:id"), {"id": node, "units": req["reserved_units"]})
                if node == req["lineage_id"]:
                    from sqlalchemy import inspect
                    if inspect(db).has_table("agent_import_cases"):
                        db.execute(text("UPDATE agent_import_cases SET model_tokens_reserved=model_tokens_reserved-:units WHERE case_id=:id"), {"id": line["case_id"], "units": req["reserved_units"]})
                    if inspect(db).has_table("agent_stage_budgets"):
                        db.execute(text("UPDATE agent_stage_budgets SET calls_used=calls_used-1,reserved_units=reserved_units-:units WHERE lineage_id=:id AND role=:role"), {"id": node, "role": req["role"], "units": req["reserved_units"]})
                node = line["parent_lineage_id"]
            self._event(db, req["authorization_id"], "REQUEST_CONFIRMED_NOT_SENT", {"request_id": request_id, "reason": reason})

    def finish_request(self, request_id, *, outcome, result):
        if outcome not in {"RESPONSE", "ERROR", "UNKNOWN"}:
            raise ValueError("Invalid request outcome")
        with self.engine.begin() as db:
            db.execute(text("UPDATE agent_authorizations SET serial=serial+1 WHERE authorization_id=(SELECT authorization_id FROM agent_request_reservations WHERE request_id=:id)"), {"id": request_id})
            row = db.execute(text("SELECT outcome,result_json FROM agent_request_reservations WHERE request_id=:id"), {"id": request_id}).mappings().one()
            value = canonical(result)
            if row["outcome"] not in {"PREPARED", "POSSIBLY_SENT"}:
                if (row["outcome"], row["result_json"]) != (outcome, value):
                    reject("MODEL_RESULT_CONFLICT", "A request result cannot be overwritten")
                return
            db.execute(text("UPDATE agent_request_reservations SET outcome=:outcome,result_json=:value WHERE request_id=:id AND outcome IN ('PREPARED','POSSIBLY_SENT')"),
                       {"id": request_id, "outcome": outcome, "value": value})

    def charge_preview(self, grant, experiment, lineage, size):
        if size < 0:
            raise ValueError("Preview usage cannot decrease")
        with self.engine.begin() as db:
            self._check(db, grant, experiment, lineage)
            seen = set()
            while lineage:
                if lineage in seen:
                    reject("LINEAGE_AUTHORIZATION_CONFLICT", "Cyclic preview lineage")
                seen.add(lineage)
                updated = db.execute(text("UPDATE agent_authorized_lineages SET preview_used=preview_used+:size WHERE lineage_id=:id AND authorization_id=:grant AND preview_used+:size<=preview_limit"), {"id": lineage, "grant": grant, "size": size})
                if updated.rowcount != 1:
                    reject("MODEL_CONTEXT_BUDGET_EXCEEDED", "Persisted lineage preview budget exhausted")
                lineage = db.execute(text("SELECT parent_lineage_id FROM agent_authorized_lineages WHERE lineage_id=:id"), {"id": lineage}).scalar()

    def status(self, grant):
        with self.engine.connect() as db:
            row = dict(db.execute(text("SELECT * FROM agent_authorizations WHERE authorization_id=:id"), {"id": grant}).mappings().one())
            contract = json.loads(row.pop("contract_json"))
            row.update(requests_remaining=contract["request_limit"] - row["calls_used"], active_seconds=self._elapsed(db, grant, self.clock()), limits=contract)
            return row

    def revoke(self, grant):
        with self.engine.begin() as db:
            db.execute(text("UPDATE agent_authorizations SET revoked=1 WHERE authorization_id=:id"), {"id": grant})
            self._event(db, grant, "REVOKED", {})

    def activate_case(self, grant, experiment, case_id, lineage):
        with self.engine.begin() as db:
            _, _, line, _ = self._check(db, grant, experiment, lineage)
            if line["case_id"] != case_id:
                reject("LINEAGE_AUTHORIZATION_CONFLICT", "Case/lineage identity differs")
            prior = db.execute(text("SELECT * FROM agent_case_authority WHERE case_id=:id"), {"id": case_id}).mappings().first()
            if prior and (prior["authorization_id"], prior["experiment_id"], prior["lineage_id"]) != (grant, experiment, lineage):
                reject("LINEAGE_AUTHORIZATION_CONFLICT", "Existing execution needs explicit recovery, not rebinding")
            if not prior:
                db.execute(text("INSERT INTO agent_case_authority (case_id,authorization_id,experiment_id,lineage_id) VALUES (:case,:grant,:experiment,:lineage)"),
                           {"case": case_id, "grant": grant, "experiment": experiment, "lineage": lineage})
            self._event(db, grant, "CASE_ACTIVATED", {"case_id": case_id, "experiment_id": experiment, "lineage_id": lineage})

    def binding(self, case_id):
        with self.engine.connect() as db:
            return db.execute(text("SELECT authorization_id,experiment_id,lineage_id FROM agent_case_authority WHERE case_id=:id"), {"id": case_id}).first()


@contextmanager
def case_authority_scope(service, case_id):
    ledger = AuthorizationLedger(service.engine)
    binding = ledger.binding(case_id)
    if binding is None:
        # Legacy/offline transitions may run, but actual model transport remains
        # denied by the default-on before_request guard.
        yield
    else:
        with authority_scope(ledger, *binding):
            yield


_AUTHORITY = ContextVar("model_authority", default=None)


@contextmanager
def authority_scope(ledger, grant, experiment, lineage):
    token = _AUTHORITY.set((ledger, grant, experiment, lineage))
    try:
        ledger.check(grant, experiment, lineage)
        yield
    finally:
        _AUTHORITY.reset(token)


def current_authority():
    return _AUTHORITY.get()


def route_identity(url, model):
    return hashlib.sha256(canonical([url.rstrip("/"), model]).encode()).hexdigest()
