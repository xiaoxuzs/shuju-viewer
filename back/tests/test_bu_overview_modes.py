from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.bu.services import overview_service


class _CountsResult:
    def mappings(self) -> "_CountsResult":
        return self

    def one(self) -> dict[str, int]:
        return {
            "matches": 0,
            "peptides": 0,
            "proteins": 0,
            "protein_groups": 0,
            "runs": 1,
            "decoy_matches": 0,
        }


class _CountsSession:
    def execute(self, *_args: Any, **_kwargs: Any) -> _CountsResult:
        return _CountsResult()


def test_raw_only_overview_does_not_read_bottom_up_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = {
        "dataset_id": 55,
        "slug": "dda_raw",
        "dataset_name": "DDA RAW",
        "status": "READY",
        "source_root": "D:\\data",
        "source_software": "DDA Thermo RAW",
        "capabilities": {
            "analysis_shape": "raw_mzml_only",
            "has_identifications": False,
        },
        "extra_metadata": {},
        "created_at": datetime(2026, 8, 26, tzinfo=timezone.utc),
    }

    monkeypatch.setattr(
        overview_service,
        "get_binary_bottom_up_overview",
        lambda *_args: pytest.fail("raw-only datasets have no BU extensions"),
    )
    monkeypatch.setattr(overview_service, "_runs", lambda *_args: [])

    overview = overview_service.get_overview(_CountsSession(), dataset)  # type: ignore[arg-type]

    assert overview.counts.matches == 0
    assert overview.counts.runs == 1
    assert overview.runs == []
