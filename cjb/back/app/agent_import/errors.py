"""Stable errors exposed by the Agent import boundary."""

from __future__ import annotations

from typing import Any


class AgentImportError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, diagnostics: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.diagnostics = diagnostics
        super().__init__(message)


class AgentSourceInvalidError(AgentImportError):
    def __init__(self, message: str) -> None:
        super().__init__("AGENT_SOURCE_INVALID", message, status_code=422)


class AgentBinaryPlanError(AgentImportError):
    def __init__(self, message: str, *, code: str = "AGENT_BINARY_PLAN_INVALID") -> None:
        super().__init__(code, message, status_code=422)
