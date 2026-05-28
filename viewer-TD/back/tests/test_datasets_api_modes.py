from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.api.v1.datasets import _dataset_out
from app.schemas import CutoffOut


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "dataset_id": 1,
        "slug": "dataset",
        "dataset_name": "Dataset",
        "description": None,
        "source_root": "D:\\data",
        "capabilities": {},
        "analysis_mode": "TOP_DOWN",
        "status": "READY",
        "source_software": "TopPIC_TopFD",
        "extra_metadata": {},
        "created_at": datetime(2026, 5, 22, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_td_dataset_json_contract_keeps_cutoffs() -> None:
    out = _dataset_out(
        row=_row(slug="mz20160222ds_histone49_html"),
        cutoffs=[
            CutoffOut(id=1, kind="prsm", label="TopPIC PrSM cutoff"),
            CutoffOut(id=2, kind="proteoform", label="TopPIC Proteoform cutoff"),
        ],
    )

    data = out.model_dump(mode="json")
    assert data["analysis_mode"] == "TOP_DOWN"
    assert data["cutoffs"][0]["kind"] == "prsm"
    assert data["cutoffs"][1]["kind"] == "proteoform"
    assert "bu_runs" not in data
