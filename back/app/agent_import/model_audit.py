"""Body-free request evidence and an optional explicit online-diagnostic budget."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import sys
from types import CodeType
import time
from datetime import datetime, timezone
from typing import Callable

from app.agent_import.errors import AgentImportError


@dataclass
class DiagnosticBudget:
    sink: Callable[[dict], None]
    remaining_calls: int
    deadline: float
    max_output: int = 4096


_BUDGET: ContextVar[DiagnosticBudget | None] = ContextVar("model_diagnostic_budget", default=None)
_SINK: ContextVar[Callable[[dict], None] | None] = ContextVar("model_request_sink", default=None)
_PHASE: ContextVar[str | None] = ContextVar("model_request_phase", default=None)


@contextmanager
def model_request_phase(name):
    token = _PHASE.set(name)
    try:
        yield
    finally:
        _PHASE.reset(token)


def code_fingerprint(code: CodeType) -> str:
    # marshal includes runtime interning details; use stable executable code/constant fields instead.
    def constant(value):
        if isinstance(value, CodeType):
            return identity(value)
        if isinstance(value, (tuple, frozenset)):
            items = [constant(item) for item in value]
            if isinstance(value, frozenset):
                items.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return {"type": type(value).__name__, "items": items}
        return {"type": type(value).__name__, "value": repr(value)}
    def identity(c):
        return {"name": c.co_name, "bytecode": c.co_code.hex(), "names": c.co_names, "locals": c.co_varnames,
                "argcount": c.co_argcount, "posonly": c.co_posonlyargcount, "kwonly": c.co_kwonlyargcount, "flags": c.co_flags,
                "freevars": c.co_freevars, "cellvars": c.co_cellvars, "exception_table": c.co_exceptiontable.hex(),
                "constants": [constant(v) for v in c.co_consts]}
    return hashlib.sha256(json.dumps(identity(code), sort_keys=True).encode()).hexdigest()


@contextmanager
def model_audit_scope(sink):
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


@contextmanager
def diagnostic_budget(sink, *, calls: int, seconds: float):
    token = _BUDGET.set(DiagnosticBudget(sink, calls, time.monotonic() + seconds))
    try:
        yield
    finally:
        _BUDGET.reset(token)


def before_request(url: str, body: dict | None, timeout: float, role: str) -> tuple[dict, float]:
    body = body or {}
    encoded = json.dumps(body, ensure_ascii=False).encode()
    cap = int(body.get("max_completion_tokens", 0))
    budget = _BUDGET.get()
    if budget:
        remaining = budget.deadline - time.monotonic()
        if budget.remaining_calls <= 0 or remaining <= 0 or cap > budget.max_output:
            raise AgentImportError("MODEL_DIAGNOSTIC_BUDGET_EXCEEDED", "Finite online diagnostic budget exhausted", status_code=409)
        budget.remaining_calls -= 1
        timeout = min(timeout, remaining)
    messages = body.get("messages", [])
    record = {"role": role, "phase": _PHASE.get() or role, "started_at": datetime.now(timezone.utc).isoformat(), "request_model": body.get("model"), "protocol": "chat_completions",
              "configuration_sha256": hashlib.sha256(json.dumps([url, body.get("model"), cap, body.get("reasoning_effort"), body.get("response_format")], sort_keys=True).encode()).hexdigest(),
              "request_bytes": len(encoded), "message_count": len(messages),
              "message_bytes": [{"role": m.get("role"), "bytes": len(json.dumps(m, ensure_ascii=False).encode())} for m in messages],
              "tools_bytes": len(json.dumps(body.get("tools", []), ensure_ascii=False).encode()),
              "output_limit": cap, "reasoning_effort": body.get("reasoning_effort"),
              "output_format": body.get("response_format"), "timeout_seconds": timeout}
    functions = {}
    for module_name, names in {
        "app.agent_import.model_provider": ["_chat_json"],
        "app.agent_import.model_routing": ["route_for"],
        "app.agent_import.kimi_research_runtime": ["KimiResearchRuntime.run", "KimiResearchRuntime._parse_blueprint", "UrllibJsonTransport.request_json"],
    }.items():
        module = sys.modules.get(module_name)
        for name in names:
            function = module
            for part in name.split("."):
                function = getattr(function, part, None)
            if hasattr(function, "__code__"):
                functions[module_name + "." + name] = code_fingerprint(function.__code__)
    record["code_fingerprint_scheme"] = "python-executable-fields-v2"
    record["loaded_code_fingerprints"] = functions
    worker_path = Path(__file__).with_name("model_http_worker.py")
    record["transport_source_sha256"] = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    from .authorization_ledger import current_authority, route_identity
    from app.core.config import settings
    from .task_runtime import current_task
    authority = current_authority()
    runtime = current_task()
    if runtime is not None:
        if not settings.openai_api_key or not settings.openai_base_url or not settings.openai_model:
            raise AgentImportError("MODEL_PROFILE_INVALID", "Configure the single OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL connection", status_code=503)
        request_id, remaining = runtime.reserve(role=role, route_sha256=route_identity(url, body.get("model")),
            request_bytes=len(encoded), output_limit=cap, request_sha256=hashlib.sha256(encoded).hexdigest())
        record.update(task_request_id=request_id, task_id=runtime.task_id)
        timeout = min(timeout, remaining)
        record["timeout_seconds"] = timeout
    elif authority is not None:
        ledger, grant, experiment, lineage = authority
        request_id, remaining = ledger.reserve(grant, experiment, lineage, role=role,
            route_sha256=route_identity(url, body.get("model")), request_bytes=len(encoded), output_limit=cap,
            request_sha256=hashlib.sha256(encoded).hexdigest())
        record["authorization_request_id"] = request_id
        record["authorization_id"] = grant
        record["experiment_id"] = experiment
        timeout = min(timeout, remaining)
        record["timeout_seconds"] = timeout
    elif settings.agent_model_authorization_required:
        raise AgentImportError("TASK_RUNTIME_REQUIRED", "Model transport requires a running task context; ordinary tasks do not require a model grant", status_code=403)
    return record, timeout


def after_request(record: dict, *, response: dict | None, error: Exception | None, elapsed: float):
    accepted = True
    record["elapsed_seconds"] = elapsed
    if response is not None:
        choices = response.get("choices") or []
        record.update({"response_model": response.get("model"), "response_id": response.get("id"),
                       "usage": response.get("usage"), "transport": response.pop("_viewer_transport", None),
                       "finish_reason": choices[0].get("finish_reason") if choices else None})
    if error is not None:
        record["error_type"] = type(error).__name__
        record["transport_timings"] = getattr(error, "transport_timings", None)
        record["transport_capture_complete"] = getattr(error, "transport_capture_complete", False)
        code = getattr(error, "code", None)
        record["error_code"] = code if isinstance(code, (str, int)) else None
    if record.get("authorization_request_id"):
        from .authorization_ledger import current_authority
        from sqlalchemy import text
        ledger = current_authority()[0]
        with ledger.engine.connect() as db:
            prepared = db.execute(text("SELECT outcome FROM agent_request_reservations WHERE request_id=:id"), {"id": record["authorization_request_id"]}).scalar() == "PREPARED"
        if prepared and response is None:
            ledger.release_unsent(record["authorization_request_id"], "Transport was not authorized to dispatch")
        else:
            ledger.finish_request(record["authorization_request_id"], outcome="RESPONSE" if response is not None else "UNKNOWN",
                result={key: record.get(key) for key in ("elapsed_seconds", "response_model", "response_id", "usage", "finish_reason", "error_type", "error_code")})
    if record.get("task_request_id"):
        from .task_runtime import current_task
        accepted = current_task().finish(record["task_request_id"], response=response is not None,
            result={key: record.get(key) for key in ("elapsed_seconds", "response_model", "response_id", "usage", "finish_reason", "error_type", "error_code")})
        record["result_accepted"] = accepted
    budget = _BUDGET.get()
    if budget:
        budget.sink(record)
    sink = _SINK.get()
    if sink:
        sink(record)
    if not sink and not budget:
        logging.getLogger(__name__).info("model_request %s", json.dumps(record))
    if not accepted:
        raise AgentImportError("WORKER_LEASE_LOST", "Late model result retained for audit but rejected for task execution", status_code=409)
