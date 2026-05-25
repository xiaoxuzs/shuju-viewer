"""Bruker TDF DIA isolation window extraction."""

from __future__ import annotations

from typing import Any

from app.bu.tdf_reader.root_resolver import resolve_run_tdf_root
from app.bu.tdf_reader.session_cache import get_session
from app.schemas import BuDiaWindowItem, BuDiaWindowsOut


def get_dia_windows(*, dataset_id: int, run: dict[str, Any]) -> BuDiaWindowsOut:
    dia = get_session(dataset_id=dataset_id, run_id=int(run["run_id"]), tdf_root=resolve_run_tdf_root(run))
    unique: dict[float, Any] = {}
    for window in dia.windows:
        key = round(float(window.isolation_mz), 2)
        unique.setdefault(key, window)
    items = [
        BuDiaWindowItem(
            mz=float(window.isolation_mz),
            width=float(window.isolation_width),
            label=f"W{index}",
        )
        for index, (_key, window) in enumerate(sorted(unique.items()), start=1)
    ]
    return BuDiaWindowsOut(run_id=int(run["run_id"]), window_count=len(items), windows=items)
