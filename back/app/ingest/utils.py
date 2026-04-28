"""Shared helpers used by the ingest pipeline."""

from __future__ import annotations

from typing import Any


def to_int(value: Any, default: int | None = None) -> int | None:
    """将 TopPIC 导出的字符串/数字安全转为 int；无法解析时返回 ``default``。"""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    """将字符串/数字安全转为 float；无法解析时返回 ``default``。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_list(value: Any) -> list:
    """TopPIC JSON sometimes collapses arrays of length 1 to a single object."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def best_prsm(prsms: list[dict[str, Any]]) -> tuple[int | None, float | None]:
    """Return (prsm_id, e_value) for the smallest e_value in ``prsms``."""
    best_id: int | None = None
    best_e: float | None = None
    for p in prsms:
        pid = to_int(p.get("prsm_id"))
        ev = to_float(p.get("e_value"))
        if pid is None:
            continue
        if best_e is None or (ev is not None and ev < best_e):
            best_id = pid
            best_e = ev
    return best_id, best_e
