"""In-process first-stage Agent worker backed by database leases."""

from __future__ import annotations

import threading
import uuid

from app.agent_import.case_service import CaseService, get_case_service
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
        poll_interval_seconds: float = 1.0,
        worker_id: str | None = None,
    ) -> None:
        self.service = service or get_case_service()
        self.workflow = workflow or AgentImportWorkflow(service=self.service)
        self.poll_interval_seconds = poll_interval_seconds
        self.worker_id = worker_id or f"agent-worker-{uuid.uuid4().hex[:8]}"
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

    def poll_once(self) -> bool:
        case = self.service.claim_next(worker_id=self.worker_id)
        if case is None:
            return False
        self.workflow.run_case(case.case_id)
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


def start_agent_worker() -> AgentWorker | None:
    global _worker
    if not settings.agent_import_enabled:
        return None
    if _worker is None:
        _worker = AgentWorker()
    _worker.start()
    return _worker


def stop_agent_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
