"""Stable errors exposed by the Agent import boundary."""

from __future__ import annotations


class AgentImportError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AgentSourceInvalidError(AgentImportError):
    def __init__(self, message: str) -> None:
        super().__init__("AGENT_SOURCE_INVALID", message, status_code=422)


class AgentBinaryPlanError(AgentImportError):
    def __init__(self, message: str) -> None:
        super().__init__("AGENT_BINARY_PLAN_INVALID", message, status_code=422)
