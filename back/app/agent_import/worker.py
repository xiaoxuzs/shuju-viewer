"""In-process first-stage Agent worker backed by database leases."""

from __future__ import annotations

import threading
import uuid
from contextlib import AbstractContextManager

from app.agent_import.case_service import CaseService, get_case_service
from app.agent_import.graph import AgentImportGraphRunner
from app.agent_import.execution_control import ExecutionFence, execution_scope
from app.agent_import.model_audit import model_audit_scope
from app.agent_import.errors import AgentImportError
from app.agent_import.workflow import AgentImportWorkflow
from app.core.config import settings
from app.core.logging import get_logger


log = get_logger(__name__)


class AgentWorker:
    def __init__(
        self,
        *,
        service: CaseService | None = None,
        workflow: AgentImportWorkflow | None = None,
        graph_runner: AgentImportGraphRunner | None = None,
        poll_interval_seconds: float = 1.0,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        legacy_experiments: bool = False,
    ) -> None:
        self.service = service or get_case_service()
        self.workflow = workflow or AgentImportWorkflow(service=self.service)
        self.graph_runner = graph_runner or AgentImportGraphRunner.for_workflow(
            service=self.service,
            workflow=self.workflow,
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.worker_id = worker_id or f"agent-worker-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.legacy_experiments = legacy_experiments
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.worker_id, daemon=True)
        self._thread.start()
        log.info("Agent worker started id=%s", self.worker_id)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._thread is None or not self._thread.is_alive():
            self.graph_runner.close()

    def poll_once(self) -> bool:
        if self.legacy_experiments:
            from .admission_policy import wake_waiting
            wake_waiting(self.service)
        case = self.service.claim_next(worker_id=self.worker_id, lease_seconds=self.lease_seconds, include_legacy=self.legacy_experiments)
        if case is None:
            from .maintenance_consumer import consume_once
            return consume_once(self.service)
        with _LeaseHeartbeat(
            service=self.service,
            case_id=case.case_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            lease_token=case.lease_token,
        ):
            if case.status.value == "STOPPING":
                self.service.finish_stopping(case.case_id)
            else:
                assert case.lease_token is not None
                fence = ExecutionFence(case.case_id, case.lease_token, lambda amount: self.service.check_execution(
                    case.case_id, case.lease_token, amount,
                ), lambda payload: self.service.record_progress(case.case_id, payload))
                from .task_runtime import case_runtime_scope
                with execution_scope(fence), model_audit_scope(lambda record: self.service.record_model_request(case.case_id, record)):
                    try:
                        with case_runtime_scope(self.service, case.case_id):
                            self.graph_runner.run_case(case.case_id)
                    except AgentImportError as exc:
                        self.workflow.handle_failure(case.case_id, exc)
        final = self.service.get_case(case.case_id)
        if final.status.value in {"SUCCESS", "FAILED", "STOPPED"}:
            from .task_runtime import TaskRuntime
            runtime = TaskRuntime(self.service.engine, case.case_id)
            if runtime.exists():
                runtime.end()
            elif self.legacy_experiments:
                from .authorization_ledger import AuthorizationLedger
                ledger = AuthorizationLedger(self.service.engine)
                binding = ledger.binding(case.case_id)
                if binding:
                    ledger.end_experiment(binding[0], binding[1], "Worker finished and owned synchronous child operations stopped: " + final.status.value)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("Agent worker poll failed")
                processed = False
            if not processed:
                self._stop.wait(self.poll_interval_seconds)


_worker: AgentWorker | None = None


class _LeaseHeartbeat(AbstractContextManager["_LeaseHeartbeat"]):
    def __init__(
        self,
        *,
        service: CaseService,
        case_id: str,
        worker_id: str,
        lease_seconds: int,
        lease_token: str | None = None,
    ) -> None:
        self.service = service
        self.case_id = case_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.lease_token = lease_token
        self.interval = max(1.0, lease_seconds / 3)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_LeaseHeartbeat":
        self._thread = threading.Thread(
            target=self._loop,
            name=f"{self.worker_id}-lease",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self.interval, 2.0))

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if not self.service.renew_lease(
                    self.case_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                    lease_token=self.lease_token,
                ):
                    return
            except Exception:  # noqa: BLE001 - the owning graph remains authoritative
                log.exception("Agent lease renewal failed case_id=%s", self.case_id)
                return


def start_agent_worker() -> AgentWorker | None:
    global _worker
    if not settings.agent_import_enabled or not settings.agent_api_worker_enabled:
        return None
    if settings.agent_candidate_verification_enabled or settings.agent_auto_delivery_enabled:
        raise RuntimeError("Privileged delivery requires AGENT_API_WORKER_ENABLED=false and the standalone Worker")
    if _worker is None:
        _worker = AgentWorker()
    _worker.start()
    return _worker


def stop_agent_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
