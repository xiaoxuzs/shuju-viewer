"""Explicit standalone entry point; no default-environment worker startup."""

from __future__ import annotations

import os
import signal
import threading


def main() -> None:
    if any(not os.environ.get(name) for name in ("VIEWER_ENV", "DATABASE_URL", "DATA_ROOT")):
        raise SystemExit("Standalone Worker requires explicit VIEWER_ENV, DATABASE_URL and DATA_ROOT")
    from app.core.config import settings
    from app.agent_import.worker import AgentWorker
    from app.agent_import.migrations import ensure_agent_import_schema

    if settings.agent_api_worker_enabled or not settings.agent_import_enabled:
        raise SystemExit("Set AGENT_API_WORKER_ENABLED=false and AGENT_IMPORT_ENABLED=true explicitly")
    ensure_agent_import_schema()
    worker = AgentWorker()
    done = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: done.set())
    worker.start()
    try:
        while not done.wait(1):
            pass
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
