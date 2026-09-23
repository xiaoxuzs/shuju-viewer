"""Non-executable engineering contract and immutable candidate materialization.

No model code is imported here. This is not a sandbox or a publication service.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_import.source_code import SourceFile, SourceSnapshot, canonical_bytes, digest_bytes, safe_relative
from app.agent_import.errors import AgentImportError
from app.agent_import.execution_control import checkpoint, current_fence


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    before_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=256_000)


class EngineeringChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    gap_artifact_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    context_revision: int = Field(ge=1)
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_role: Literal["initial_implementation", "maintenance_checker"]
    semantics: str = Field(min_length=1, max_length=4000)
    changes: list[FileChange] = Field(min_length=1, max_length=20)
    checks: list[Literal["backend_tests", "frontend_build"]] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_paths(self):
        names = [safe_relative(c.path).casefold() for c in self.changes]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate/case-colliding patch paths")
        return self

    @property
    def operation_key(self):
        return digest_bytes(canonical_bytes(self.model_dump(mode="json")))


_EDIT_PREFIXES = ("back/app/ingest/", "back/app/declarative_ingest/", "back/app/bu/", "back/app/api/v1/bu/", "front/src/features/bu/")
_PROTECTED_NAMES = {"preflight.py", "semantic_schema.py", "contracts.py", "zp_artifact.py", "__init__.py"}


def apply_change(snapshot: SourceSnapshot, change: EngineeringChange, *, allowed_paths: frozenset[str], ever_published: bool) -> SourceSnapshot:
    if snapshot.identity != change.baseline_sha256:
        raise ValueError("Engineering baseline changed")
    if ever_published and change.decision_role != "maintenance_checker":
        raise ValueError("Published work cannot invoke the initial implementation role")
    files = {f.relative_path: f for f in snapshot.files}
    for edit in change.changes:
        path = safe_relative(edit.path)
        if path not in allowed_paths or not path.startswith(_EDIT_PREFIXES) or Path(path).name.casefold() in _PROTECTED_NAMES:
            raise ValueError("Patch touches a protected or unapproved path")
        if any(part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))} for part in Path(path).parts):
            raise ValueError("Reserved device path")
        if any(p.casefold() == path.casefold() and p != path for p in files):
            raise ValueError("Patch path case aliases an existing file")
        if Path(path).suffix not in {".py", ".ts", ".tsx", ".css"}:
            raise ValueError("Unsupported patch file type")
        old = files.get(path)
        if (old.sha256 if old else None) != edit.before_sha256:
            raise ValueError("Patch preimage does not match the actual working-copy snapshot")
        content = edit.content.encode("utf-8")
        files[path] = SourceFile(path, digest_bytes(content), content)
    return SourceSnapshot(tuple(files[p] for p in sorted(files)))


def execute_engineering_change(service, change: EngineeringChange, snapshot: SourceSnapshot, *, runner, allowed_paths, output_root: Path):
    """Trusted existing-Worker operation ledger; deliberately not a new scheduler/API.

    A recorded execution never activates code/capabilities or resumes a data node.
    That requires independent acceptance and is not implemented by this function.
    """
    from sqlalchemy import text
    from app.agent_import.case_service import _now
    import json
    fence = current_fence()
    if fence is None or fence.case_id != change.case_id:
        raise AgentImportError("WORKER_LEASE_REQUIRED", "Engineering execution is internal to a claimed Worker", status_code=403)
    checkpoint()
    with service.engine.begin() as connection:
        service._guard_execution(connection, change.case_id)
        case = service._locked_case(connection, change.case_id)
        if case.context_revision != change.context_revision:
            raise AgentImportError("SOURCE_CODE_CHANGED", "Engineering context revision changed", status_code=409)
        candidate = apply_change(snapshot, change, allowed_paths=allowed_paths, ever_published=case.ever_published)
        previous = connection.execute(text("SELECT state FROM agent_engineering_operations WHERE operation_key=:key"), {"key": change.operation_key}).first()
        if previous:
            raise AgentImportError("SANDBOX_RECONCILIATION_REQUIRED", "This operation already has a ledger entry; do not repeat side effects", status_code=409)
        connection.execute(text("INSERT INTO agent_engineering_operations (operation_key,case_id,context_revision,lease_token,state,candidate_sha256) VALUES (:key,:case,:revision,:token,'RUNNING',:sha)"),
            {"key": change.operation_key, "case": change.case_id, "revision": change.context_revision, "token": fence.token, "sha": candidate.identity})
        service._insert_json_artifact_tx(connection, case, None, "engineering_change", change.model_dump(mode="json"), _now())
    results = []
    try:
        for check in change.checks:
            checkpoint()
            key = digest_bytes(canonical_bytes([change.operation_key, check]))
            result = runner.run(candidate, output_root / key, operation_key=key, check=check)
            results.append(result)
            if result.get("exit_code") != 0:
                break
        checkpoint()
        state = "EXECUTED_NOT_ACCEPTED" if all(r.get("exit_code") == 0 for r in results) else "EXECUTION_FAILED"
    except Exception as exc:
        state = "BLOCKED" if getattr(exc, "code", "") == "SANDBOX_NOT_ADMITTED" else "RECONCILIATION_REQUIRED"
        results.append({"error_type": type(exc).__name__, "code": getattr(exc, "code", None)})
        # Cancelled/taken-over Worker must NOT register an error as a successful reconciliation.
        checkpoint()
    with service.engine.begin() as connection:
        service._guard_execution(connection, change.case_id)
        case = service._locked_case(connection, change.case_id)
        if case.context_revision != change.context_revision:
            raise AgentImportError("SOURCE_CODE_CHANGED", "Engineering result became stale", status_code=409)
        connection.execute(text("UPDATE agent_engineering_operations SET state=:state,result_json=:result WHERE operation_key=:key AND lease_token=:token"),
            {"state": state, "result": json.dumps(results), "key": change.operation_key, "token": fence.token})
        service._insert_json_artifact_tx(connection, case, None, "engineering_execution", {
            "operation_key": change.operation_key, "state": state, "results": results,
            "candidate_sha256": candidate.identity, "capability_activated": False,
        }, _now())
    return {"state": state, "operation_key": change.operation_key, "candidate_sha256": candidate.identity}
