"""Resolve active .zp artifacts for Viewer datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class ActiveZpAsset:
    asset_id: int
    dataset_id: int
    run_id: int | None
    zp_path: Path
    format_version: int
    capabilities: dict[str, Any]


def find_active_asset(
    session: Session,
    dataset_id: int,
    *,
    run_id: int | None = None,
) -> ActiveZpAsset | None:
    if not settings.zp_management_enabled:
        # Default server deploys do not create optional ZP tables, so ordinary
        # dataset views must behave as if no binary artifact is present.
        return None
    row = session.execute(
        text(
            """
            SELECT asset_id, dataset_id, run_id, zp_path, format_version, capabilities
            FROM dataset_zp_assets
            WHERE dataset_id = :dataset_id
              AND status = 'active'
              AND (:run_id IS NULL OR run_id IS NULL OR run_id = :run_id)
            ORDER BY CASE WHEN run_id = :run_id THEN 0 ELSE 1 END, asset_id DESC
            LIMIT 1
            """
        ),
        {"dataset_id": dataset_id, "run_id": run_id},
    ).mappings().one_or_none()
    if row is None:
        return None
    return ActiveZpAsset(
        asset_id=int(row["asset_id"]),
        dataset_id=int(row["dataset_id"]),
        run_id=_int_or_none(row.get("run_id")),
        zp_path=Path(str(row["zp_path"])),
        format_version=int(row["format_version"]),
        capabilities=_json_object(row.get("capabilities")),
    )


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None
