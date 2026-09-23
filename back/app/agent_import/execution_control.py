"""Worker-scoped cancellation/deadline checks, backed by the existing Case row."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionFence:
    case_id: str
    token: str
    check: Callable[[int], float]
    progress: Callable[[dict], None] | None = None


_CURRENT: ContextVar[ExecutionFence | None] = ContextVar("agent_execution", default=None)


@contextmanager
def execution_scope(fence: ExecutionFence) -> Iterator[None]:
    value = _CURRENT.set(fence)
    try:
        yield
    finally:
        _CURRENT.reset(value)


def current_fence() -> ExecutionFence | None:
    return _CURRENT.get()


def report_progress(phase: str, processed: int | None = None, total: int | None = None):
    fence = _CURRENT.get()
    if fence is not None and fence.progress is not None:
        checkpoint()
        fence.progress({"phase": phase, "processed": processed, "total": total,
                        "remaining": max(0, total - processed) if total is not None and processed is not None else None})


def checkpoint(reserve_tokens: int = 0, *, timeout: float = 60) -> float:
    from .task_runtime import current_task
    runtime = current_task()
    if runtime is not None:
        timeout = min(timeout, runtime.check())
    from .authorization_ledger import current_authority
    authority = current_authority()
    if authority is not None:
        ledger, grant, experiment, lineage = authority
        timeout = min(timeout, ledger.check(grant, experiment, lineage))
    fence = _CURRENT.get()
    if fence is None:
        return timeout
    remaining = fence.check(reserve_tokens)
    return max(0.001, min(timeout, remaining))
