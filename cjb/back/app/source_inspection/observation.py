"""Observation construction and scoped hashing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import BudgetTracker
from .contracts import ObservationArtifact, ObservationHashes, ObservationStatus, TruncationInfo


@dataclass(frozen=True)
class InspectionOutcome:
    status: ObservationStatus
    facts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    truncation_reasons: list[str] = field(default_factory=list)
    source_content_sha256: str | None = None


def finalize_observation(
    *,
    path: Path,
    relative_path: str,
    detected_format: str,
    inspector_id: str,
    inspector_version: str,
    tracker: BudgetTracker,
    outcome: InspectionOutcome,
) -> ObservationArtifact:
    stat_result = path.stat()
    usage = tracker.usage()
    reasons = list(outcome.truncation_reasons)
    reasons.extend(f"budget_{reason}" for reason in usage.exhausted)
    reasons = list(dict.fromkeys(reasons))
    status = outcome.status
    if status == "COMPLETE" and usage.exhausted:
        status = "PARTIAL"
    warnings = [
        warning.replace(str(path), relative_path).replace(path.as_posix(), relative_path)
        for warning in outcome.warnings
    ]

    source_metadata_payload = (
        f"{relative_path}|{int(stat_result.st_size)}|{int(stat_result.st_mtime_ns)}"
    ).encode("utf-8")
    source_metadata_sha256 = hashlib.sha256(source_metadata_payload).hexdigest()
    hash_payload = {
        "schema_version": 1,
        "status": status,
        "relative_path": relative_path,
        "source_size_bytes": int(stat_result.st_size),
        "source_mtime_ns": int(stat_result.st_mtime_ns),
        "detected_format": detected_format,
        "inspector_id": inspector_id,
        "inspector_version": inspector_version,
        "facts": outcome.facts,
        "warnings": warnings,
        "budget": usage.model_dump(mode="json"),
        "truncation": {"truncated": bool(reasons), "reasons": reasons},
        "hashes": {
            "source_metadata_sha256": source_metadata_sha256,
            "inspection_sample_sha256": tracker.sample_sha256,
            "source_content_sha256": outcome.source_content_sha256,
            "inspection_sample_scope": "bytes-read-in-inspection-order",
        },
    }
    canonical = json.dumps(
        hash_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    hashes = ObservationHashes(
        source_metadata_sha256=source_metadata_sha256,
        inspection_sample_sha256=tracker.sample_sha256,
        observation_sha256=hashlib.sha256(canonical).hexdigest(),
        source_content_sha256=outcome.source_content_sha256,
    )
    return ObservationArtifact(
        status=status,
        relative_path=relative_path,
        source_size_bytes=int(stat_result.st_size),
        source_mtime_ns=int(stat_result.st_mtime_ns),
        detected_format=detected_format,
        inspector_id=inspector_id,
        inspector_version=inspector_version,
        facts=outcome.facts,
        warnings=warnings,
        budget=usage,
        truncation=TruncationInfo(truncated=bool(reasons), reasons=reasons),
        hashes=hashes,
    )
