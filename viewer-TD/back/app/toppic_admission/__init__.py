"""TopPIC dataset file discrimination (admission) for path imports."""

from __future__ import annotations

from pathlib import Path

from app.dataset_ingest_root import resolve_ingest_root

from .classify import classify_admission, classify_from_signals
from .signals import collect_signals
from .orchestrate import AdaptResult, run_pfmb_adapt
from .types import (
    AdmissionDecision,
    AdmissionRoute,
    DirectIngestShape,
    PfmbIngestSource,
    RunTriple,
)

__all__ = [
    "AdaptResult",
    "AdmissionDecision",
    "AdmissionRoute",
    "DirectIngestShape",
    "PfmbIngestSource",
    "RunTriple",
    "classify_admission",
    "classify_from_signals",
    "classify_user_path",
    "collect_signals",
    "run_pfmb_adapt",
]


def classify_user_path(user_selected: Path | str) -> AdmissionDecision:
    """Resolve ingest root, then classify admission."""
    ingest_root = resolve_ingest_root(user_selected)
    return classify_admission(ingest_root)
