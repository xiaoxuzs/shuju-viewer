"""Bottom-Up Bruker mobility slice service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.bu.tdf_reader import mobility_slice as tdf_mobility_slice
from app.bu.tdf_reader.session_cache import TdfpyUnavailable
from app.schemas import BuMobilitySliceOut


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def get_match_mobility_slice(dataset: dict[str, Any], match: dict[str, Any]) -> BuMobilitySliceOut:
    run_meta = _json_object(match.get("run_metadata"))
    if str(run_meta.get("raw_format") or "").lower() != "bruker_d":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unsupported_raw_format")
    rt_apex = _rt_apex(match)
    if rt_apex is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mobility_slice_not_found")
    run = {
        "run_id": int(match["run_id"]),
        "file_path": match.get("file_path"),
        "run_metadata": run_meta,
    }
    try:
        return tdf_mobility_slice.get_mobility_slice(
            dataset_id=int(dataset["dataset_id"]),
            run=run,
            rt_apex=rt_apex,
        )
    except TdfpyUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="tdfpy_unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc) or "tdf_not_found") from exc


def _rt_apex(match: dict[str, Any]) -> float | None:
    extra = _json_object(match.get("extra_metadata"))
    for key in ("rt_apex", "RT", "rt"):
        value = extra.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    value = match.get("retention_time")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
