"""Deterministic admission before an unknown-format Case is created."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agent_import.errors import AgentSourceInvalidError
from app.fingerprint import compute_dataset_metadata_fingerprint


@dataclass(frozen=True, slots=True)
class AgentCaseAdmission:
    source_root: Path
    dataset_fingerprint: str
    file_count: int


def admit_unknown_source_path(source_path: str | Path) -> AgentCaseAdmission:
    selected = Path(source_path).expanduser()
    try:
        source_root = selected.resolve(strict=True)
    except OSError as exc:
        raise AgentSourceInvalidError(f"source_path must be an existing directory: {selected}") from exc
    if not source_root.is_dir():
        raise AgentSourceInvalidError(f"source_path must be an existing directory: {source_root}")

    fingerprint = compute_dataset_metadata_fingerprint(source_root)
    if fingerprint.file_count == 0:
        raise AgentSourceInvalidError("source_path is empty")
    return AgentCaseAdmission(
        source_root=source_root,
        dataset_fingerprint=fingerprint.fingerprint,
        file_count=fingerprint.file_count,
    )
