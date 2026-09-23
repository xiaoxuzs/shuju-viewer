"""Existing Case/Worker engineering consumer. No sandbox => no model code proposal/execution."""
import json

from app.agent_import.contracts import CapabilityGap
from app.agent_import.engineering import execute_engineering_change
from app.agent_import.errors import AgentImportError
from app.agent_import.execution_control import checkpoint, current_fence
from app.agent_import.failure_policy import AgentFailureClass
from app.agent_import.source_code import SourceSnapshot
from app.core.config import settings


def consume_engineering_case(workflow, case_id):
    case = workflow.service.get_case(case_id)
    if not settings.agent_engineering_enabled or current_fence() is None or case.status.value != "ENGINEERING":
        raise AgentImportError("ENGINEERING_NOT_AUTHORIZED", "Engineering requires an enabled claimed Case", status_code=403)
    if case.ever_published or case.dataset_id is not None:
        raise AgentImportError("PUBLISHED_CASE_ROLE_FORBIDDEN", "Published history requires the not-yet-enabled maintenance consumer", status_code=409)
    checkpoint()
    requests = [a for a in workflow.service.list_artifacts(case_id) if a.artifact_type == "capability_gap"]
    if not requests:
        raise AgentImportError("CAPABILITY_GAP", "Engineering has no persisted capability gap", status_code=409)
    request = requests[-1]
    gap = CapabilityGap.model_validate(request.structured_payload)
    if gap.candidate_context_revision != case.context_revision:
        raise AgentImportError("SOURCE_CODE_CHANGED", "Engineering context changed", status_code=409)
    runner = workflow.engineering_runner
    if runner is None:
        workflow.service._record_json_artifact(case_id, "engineering_gate", {"state": "BLOCKED", "code": "SANDBOX_NOT_ADMITTED",
            "gap_artifact_id": request.artifact_id, "context_revision": case.context_revision, "model_invoked": False})
        raise AgentImportError("SANDBOX_NOT_ADMITTED", "No independently verified sandbox is configured; no host fallback", status_code=503)
    runner.require_admission()
    if not settings.agent_implementation_source_evidence_enabled:
        raise AgentImportError("SOURCE_EVIDENCE_EGRESS_NOT_AUTHORIZED", "Engineering source egress is not authorized", status_code=403)
    allowed = frozenset(json.loads(settings.agent_engineering_allowed_paths_json))
    if not allowed or len(allowed) > 20:
        raise AgentImportError("ENGINEERING_NOT_AUTHORIZED", "Operator must specify at most20 exact patch paths", status_code=403)
    snapshot = SourceSnapshot.capture(settings.agent_source_root)
    context = workflow._context(case, {})
    proposal = workflow.provider.propose_engineering_change(context, gap.model_dump(mode="json"), request.artifact_id, snapshot, allowed)
    if proposal.case_id != case_id or proposal.context_revision != case.context_revision or proposal.decision_role != "initial_implementation":
        raise AgentImportError("ENGINEERING_CONTRACT_INVALID", "Engineering proposal changed scope/role", status_code=422)
    result = execute_engineering_change(workflow.service, proposal, snapshot, runner=runner, allowed_paths=allowed,
        output_root=settings.resolved_zp_output_root / "agent-cases" / case_id / "engineering")
    # Execution alone cannot activate an app version. No hot-import, fake registration or restart.
    return workflow.service.record_failure(case_id, code="ENGINEERING_ACCEPTANCE_REQUIRED", failure_class=AgentFailureClass.ENGINEERING_REVIEW,
        summary="Engineering operation recorded; independent acceptance and version activation are required before resuming the affected data node.", diagnostics=result)
