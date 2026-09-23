"""Stable routing classes for Agent scientific and infrastructure failures."""

from __future__ import annotations

from enum import Enum


class AgentFailureClass(str, Enum):
    USER_INPUT = "USER_INPUT"
    SCIENTIFIC = "SCIENTIFIC"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    INFRASTRUCTURE = "INFRASTRUCTURE"


_USER_INPUT_CODES = frozenset(
    {
        "SOURCE_ROLE_UNKNOWN",
        "UNIT_AMBIGUOUS",
        "RUN_ASSOCIATION_AMBIGUOUS",
        "MISSING_REQUIRED_COMPANION_FILE",
        "SCIENTIFIC_SEMANTIC_UNKNOWN",
    }
)
_ENGINEERING_CODES = frozenset(
    {
        "AGENT_CANDIDATE_SCHEMA_INVALID",
        "DECLARATIVE_PLAN_INVALID",
        "VERIFICATION_SOURCE_RULE_UNAVAILABLE",
        "DECLARATIVE_EXECUTION_FAILED",
        "ADAPTER_FIELD_MAPPING_FAILED",
        "AGENT_DIAGNOSTIC_WRITE_FAILED",
        "FORMAT_REVIEW_REQUIRED",
        "VALIDATOR_CHANGE_REQUESTED",
        "CORE_BLOCK_CHANGE_REQUIRED",
        "DEFAULT_VERSION_CHANGE_REQUIRED",
        "NEW_BINARY_ENCODING_REQUIRED",
        "SOURCE_CHANGED",
        "SOURCE_CODE_CHANGED",
        "AGENT_ZP_UNSUPPORTED_BUSINESS_EXTENSION",
        "CAPABILITY_GAP",
        "PUBLISHED_CASE_ROLE_FORBIDDEN",
        "AUTO_DELIVERY_NOT_AUTHORIZED",
        "SOURCE_EVIDENCE_EGRESS_NOT_AUTHORIZED",
    }
)
_INFRASTRUCTURE_CODES = frozenset(
    {
        "MODEL_PROVIDER_UNAVAILABLE",
        "RESEARCH_UNAVAILABLE",
        "WORKER_LEASE_LOST",
        "DATABASE_UNAVAILABLE",
        "SANDBOX_START_FAILED",
        "DISK_SPACE_LOW",
        "AGENT_REVIEW_PROVIDER_MISSING",
        "AGENT_DEADLINE_EXCEEDED",
        "AGENT_BUDGET_EXCEEDED",
        "AGENT_MEMORY_BUDGET_EXCEEDED",
        "APPLICATION_VERIFICATION_NOT_CONFIGURED",
        "APPLICATION_VALIDATION_FAILED",
        "VERIFICATION_BASELINE_REQUIRED",
        "APPLICATION_VALIDATION_COVERAGE_MISSING",
        "APPLICATION_VERIFICATION_REQUIRED",
        "APPLICATION_VERIFICATION_STALE",
        "VERIFICATION_RECONCILIATION_REQUIRED",
    }
)


def classify_agent_failure(exc: Exception) -> AgentFailureClass:
    code = str(getattr(exc, "code", "")).upper()
    if code in _USER_INPUT_CODES:
        return AgentFailureClass.USER_INPUT
    if code in _ENGINEERING_CODES or code.startswith("ENGINEERING_"):
        return AgentFailureClass.ENGINEERING_REVIEW
    if code in _INFRASTRUCTURE_CODES or code.startswith(("TASK_", "MODEL_", "DATABASE_", "WORKER_", "SANDBOX_", "AUTHORIZATION_", "EXPERIMENT_", "LINEAGE_")):
        return AgentFailureClass.INFRASTRUCTURE
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return AgentFailureClass.INFRASTRUCTURE
    return AgentFailureClass.SCIENTIFIC
