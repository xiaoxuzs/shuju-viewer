"""Deterministic Agent Case states and legal transitions."""

from __future__ import annotations

from enum import Enum


class CaseStatus(str, Enum):
    CREATED = "CREATED"
    WAITING_AUTHORIZATION = "WAITING_AUTHORIZATION"
    ANALYZING = "ANALYZING"
    STRATEGY_READY = "STRATEGY_READY"
    BUILDING = "BUILDING"
    ENGINEERING = "ENGINEERING"
    VERIFYING = "VERIFYING"
    NEEDS_USER = "NEEDS_USER"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    DELIVERING = "DELIVERING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class InteractionMode(str, Enum):
    AUTONOMOUS = "autonomous"
    GUIDED = "guided"


TERMINAL_STATUSES = frozenset({CaseStatus.SUCCESS, CaseStatus.FAILED, CaseStatus.STOPPED})

_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.WAITING_AUTHORIZATION: frozenset({CaseStatus.CREATED, CaseStatus.ANALYZING, CaseStatus.BUILDING, CaseStatus.STRATEGY_READY, CaseStatus.VERIFYING, CaseStatus.DELIVERING, CaseStatus.STOPPED}),
    CaseStatus.CREATED: frozenset({CaseStatus.ANALYZING, CaseStatus.STOPPED}),
    CaseStatus.ANALYZING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.STRATEGY_READY, CaseStatus.NEEDS_USER, CaseStatus.FAILED, CaseStatus.STOPPING}
    ),
    CaseStatus.STRATEGY_READY: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.BUILDING, CaseStatus.ENGINEERING, CaseStatus.NEEDS_USER, CaseStatus.FAILED, CaseStatus.STOPPING}
    ),
    CaseStatus.ENGINEERING: frozenset({CaseStatus.FAILED, CaseStatus.STOPPING}),
    CaseStatus.BUILDING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.STRATEGY_READY, CaseStatus.VERIFYING, CaseStatus.NEEDS_USER, CaseStatus.FAILED, CaseStatus.STOPPING}
    ),
    CaseStatus.VERIFYING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.NEEDS_USER, CaseStatus.READY_FOR_REVIEW, CaseStatus.FAILED, CaseStatus.STOPPING}
    ),
    CaseStatus.NEEDS_USER: frozenset({CaseStatus.ANALYZING, CaseStatus.STOPPED}),
    CaseStatus.READY_FOR_REVIEW: frozenset({CaseStatus.ANALYZING, CaseStatus.VERIFYING, CaseStatus.SUCCESS, CaseStatus.STOPPED, CaseStatus.DELIVERING, CaseStatus.FAILED}),
    CaseStatus.DELIVERING: frozenset({CaseStatus.SUCCESS, CaseStatus.FAILED, CaseStatus.STOPPING}),
    CaseStatus.STOPPING: frozenset({CaseStatus.STOPPED}),
    CaseStatus.SUCCESS: frozenset(),
    CaseStatus.FAILED: frozenset({CaseStatus.STRATEGY_READY}),  # Only the guarded unpublished recovery service admits this.
    CaseStatus.STOPPED: frozenset(),
}


def assert_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target == CaseStatus.WAITING_AUTHORIZATION and current not in TERMINAL_STATUSES:
        return
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"illegal Agent Case transition: {current.value} -> {target.value}")
