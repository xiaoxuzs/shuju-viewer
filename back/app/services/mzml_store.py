"""Legacy per-run mzML cache (deprecated).

Canonical implementation: :mod:`app.spectrum_memory` (dataset-level bundle,
global byte budget, MRU/LRU). This module is kept for reference and for the
parsing helpers pattern; new code should use ``spectrum_memory`` + wiring.
"""

from __future__ import annotations

import gzip
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyteomics import mzml


_SCAN_RE = re.compile(r"scan=(\d+)")


def _parse_scan(native_id: str) -> int | None:
    m = _SCAN_RE.search(native_id or "")
    return int(m.group(1)) if m else None


def _rt_seconds(spec: dict[str, Any]) -> float:
    for s in spec.get("scanList", {}).get("scan", []):
        t = s.get("scan start time")
        if t is None:
            continue
        unit = str(getattr(t, "unit_info", "")).lower()
        val = float(t)
        return val * 60.0 if "minute" in unit else val
    return 0.0


def _extract_precursor(spec: dict[str, Any]) -> dict[str, Any] | None:
    precs = spec.get("precursorList", {}).get("precursor", [])
    if not precs:
        return None
    p = precs[0]
    iso = p.get("isolationWindow", {}) or {}
    sel_list = p.get("selectedIonList", {}).get("selectedIon", [])
    sel = sel_list[0] if sel_list else {}

    parent_scan = _parse_scan(p.get("spectrumRef") or "")

    def _f(d: dict[str, Any], *keys: str) -> float | None:
        for k in keys:
            if k in d and d[k] is not None:
                try:
                    return float(d[k])
                except (TypeError, ValueError):
                    return None
        return None

    def _i(d: dict[str, Any], *keys: str) -> int | None:
        v = _f(d, *keys)
        return int(v) if v is not None else None

    return {
        "parent_scan": parent_scan,
        "target_mz": _f(iso, "isolation window target m/z"),
        "lower_offset": _f(iso, "isolation window lower offset"),
        "upper_offset": _f(iso, "isolation window upper offset"),
        "selected_mz": _f(sel, "selected ion m/z"),
        "charge": _i(sel, "charge state"),
    }


def _extract_spectrum(spec: dict[str, Any], scan: int) -> dict[str, Any]:
    mz_arr = spec.get("m/z array")
    int_arr = spec.get("intensity array")
    return {
        "scan": scan,
        "native_id": spec.get("id"),
        "ms_level": int(spec.get("ms level", 1)),
        "rt_seconds": _rt_seconds(spec),
        "mz": mz_arr.tolist() if mz_arr is not None else [],
        "intensity": int_arr.tolist() if int_arr is not None else [],
        "precursor": _extract_precursor(spec),
    }


@dataclass
class _RunCache:
    path: Path
    spectra: dict[int, dict[str, Any]]


class MzmlStore:
    """Process-global cache for mzML files, keyed by run_id."""

    def __init__(self, *, max_runs: int = 4) -> None:
        self._max_runs = max(1, int(max_runs))
        self._lock = threading.RLock()
        self._loading: dict[int, threading.Event] = {}
        self._cache: dict[int, _RunCache] = {}
        self._lru: list[int] = []

    def _touch(self, run_id: int) -> None:
        if run_id in self._lru:
            self._lru.remove(run_id)
        self._lru.append(run_id)

    def _evict_if_needed(self) -> None:
        while len(self._lru) > self._max_runs:
            victim = self._lru.pop(0)
            self._cache.pop(victim, None)

    def is_loaded(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._cache

    def status(self, run_id: int) -> dict[str, Any]:
        with self._lock:
            c = self._cache.get(run_id)
            if c is None:
                return {"run_id": run_id, "loaded": False, "path": None, "loaded_scans": 0, "ms1_count": 0, "ms2_count": 0}
            return {
                "run_id": run_id,
                "loaded": True,
                "path": str(c.path),
                "loaded_scans": len(c.spectra),
                "ms1_count": sum(1 for s in c.spectra.values() if s.get("ms_level") == 1),
                "ms2_count": sum(1 for s in c.spectra.values() if s.get("ms_level") == 2),
            }

    def load_run(self, *, run_id: int, mzml_path: Path) -> None:
        """Load and index a mzML file for this run_id (blocking)."""
        mzml_path = mzml_path.resolve()
        with self._lock:
            existing = self._cache.get(run_id)
            if existing is not None and existing.path == mzml_path:
                self._touch(run_id)
                return

            evt = self._loading.get(run_id)
            if evt is not None:
                is_loader = False
            else:
                evt = threading.Event()
                self._loading[run_id] = evt
                is_loader = True

        if not is_loader:
            evt.wait()
            return

        # We are the loader for this run_id; ensure waiters always unblock.
        spectra: dict[int, dict[str, Any]] = {}
        try:
            lower = str(mzml_path).lower()
            if lower.endswith(".mzml.gz") or lower.endswith(".mzml.gzip"):
                with gzip.open(mzml_path, "rb") as fh:
                    with mzml.read(fh) as reader:
                        for spec in reader:
                            scan = _parse_scan(spec.get("id", ""))
                            if scan is None:
                                continue
                            spectra[scan] = _extract_spectrum(spec, scan)
            else:
                with mzml.read(str(mzml_path)) as reader:
                    for spec in reader:
                        scan = _parse_scan(spec.get("id", ""))
                        if scan is None:
                            continue
                        spectra[scan] = _extract_spectrum(spec, scan)
        finally:
            with self._lock:
                done_evt = self._loading.pop(run_id, None)
                if done_evt is not None:
                    done_evt.set()

        with self._lock:
            # If parsing failed and raised, we won't reach here.
            self._cache[run_id] = _RunCache(path=mzml_path, spectra=spectra)
            self._touch(run_id)
            self._evict_if_needed()

    def get_spectrum(self, *, run_id: int, scan_number: int) -> dict[str, Any] | None:
        with self._lock:
            c = self._cache.get(run_id)
            if c is None:
                return None
            self._touch(run_id)
            return c.spectra.get(scan_number)


STORE = MzmlStore()

