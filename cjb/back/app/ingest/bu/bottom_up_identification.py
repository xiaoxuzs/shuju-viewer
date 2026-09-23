"""Narrow source-neutral input contract for Bottom-Up DIA ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BottomUpIdentification:
    """One accepted identification plus the DIA-NN row used as display context."""

    report_row: dict[str, Any]
    score: float | None
    q_value: float | None
    intensity: float | None
    pep: float | None
    search_engine: str
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BottomUpSource:
    """Prepared source rows and dataset-level provenance for the shared writer."""

    software: str
    import_mode: str
    dataset_description: str
    identifications: list[BottomUpIdentification]
    source_total_rows: int
    skipped_matches: int
    extra_metadata: dict[str, Any] = field(default_factory=dict)
