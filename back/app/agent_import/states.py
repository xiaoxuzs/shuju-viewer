"""Deterministic Agent Case states and legal transitions."""

from __future__ import annotations

from enum import Enum


class CaseStatus(str, Enum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    STRATEGY_READY = "STRATEGY_READY"
    BUILDING = "BUILDING"
    VERIFYING = "VERIFYING"
    NEEDS_USER = "NEEDS_USER"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class InteractionMode(str, Enum):
    AUTONOMOUS = "autonomous"
    GUIDED = "guided"


TERMINAL_STATUSES = frozenset({CaseStatus.SUCCESS, CaseStatus.FAILED, CaseStatus.STOPPED})

_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.CREATED: frozenset({CaseStatus.ANALYZING, CaseStatus.STOPPED}),
    CaseStatus.ANALYZING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.STRATEGY_READY, CaseStatus.NEEDS_USER, CaseStatus.STOPPING}
    ),
    CaseStatus.STRATEGY_READY: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.BUILDING, CaseStatus.NEEDS_USER, CaseStatus.STOPPING}
    ),
    CaseStatus.BUILDING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.VERIFYING, CaseStatus.NEEDS_USER, CaseStatus.STOPPING}
    ),
    CaseStatus.VERIFYING: frozenset(
        {CaseStatus.ANALYZING, CaseStatus.NEEDS_USER, CaseStatus.READY_FOR_REVIEW, CaseStatus.STOPPING}
    ),
    CaseStatus.NEEDS_USER: frozenset({CaseStatus.ANALYZING, CaseStatus.STOPPED}),
    CaseStatus.READY_FOR_REVIEW: frozenset({CaseStatus.ANALYZING, CaseStatus.SUCCESS, CaseStatus.STOPPED}),
    CaseStatus.STOPPING: frozenset({CaseStatus.STOPPED}),
    CaseStatus.SUCCESS: frozenset(),
    CaseStatus.FAILED: frozenset(),
    CaseStatus.STOPPED: frozenset(),
}


def assert_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"illegal Agent Case transition: {current.value} -> {target.value}")
