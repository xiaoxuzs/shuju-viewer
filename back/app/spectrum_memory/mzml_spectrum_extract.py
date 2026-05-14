"""Parse mzML into per-scan spectrum dicts (no global cache; used by DatasetMzmlBundle)."""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path
from typing import Any

from pyteomics import mzml

_SCAN_RE = re.compile(r"scan=(\d+)")


def parse_scan(native_id: str) -> int | None:
    m = _SCAN_RE.search(native_id or "")
    return int(m.group(1)) if m else None


def rt_seconds(spec: dict[str, Any]) -> float:
    for s in spec.get("scanList", {}).get("scan", []):
        t = s.get("scan start time")
        if t is None:
            continue
        unit = str(getattr(t, "unit_info", "")).lower()
        val = float(t)
        return val * 60.0 if "minute" in unit else val
    return 0.0


def extract_precursor(spec: dict[str, Any]) -> dict[str, Any] | None:
    precs = spec.get("precursorList", {}).get("precursor", [])
    if not precs:
        return None
    p = precs[0]
    iso = p.get("isolationWindow", {}) or {}
    sel_list = p.get("selectedIonList", {}).get("selectedIon", [])
    sel = sel_list[0] if sel_list else {}

    parent_scan = parse_scan(p.get("spectrumRef") or "")

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


def extract_spectrum(spec: dict[str, Any], scan: int) -> dict[str, Any]:
    mz_arr = spec.get("m/z array")
    int_arr = spec.get("intensity array")
    return {
        "scan": scan,
        "native_id": spec.get("id"),
        "ms_level": int(spec.get("ms level", 1)),
        "rt_seconds": rt_seconds(spec),
        "mz": mz_arr.tolist() if mz_arr is not None else [],
        "intensity": int_arr.tolist() if int_arr is not None else [],
        "precursor": extract_precursor(spec),
    }


def load_mzml_path_to_scan_map(path: Path) -> dict[int, dict[str, Any]]:
    """Read entire mzML once; return scan_number -> spectrum payload."""
    path = path.resolve()
    spectra: dict[int, dict[str, Any]] = {}
    lower = str(path).lower()
    if lower.endswith(".mzml.gz") or lower.endswith(".mzml.gzip"):
        with gzip.open(path, "rb") as fh:
            with mzml.read(fh) as reader:
                for spec in reader:
                    scan = parse_scan(spec.get("id", ""))
                    if scan is None:
                        continue
                    spectra[scan] = extract_spectrum(spec, scan)
    else:
        with mzml.read(str(path)) as reader:
            for spec in reader:
                scan = parse_scan(spec.get("id", ""))
                if scan is None:
                    continue
                spectra[scan] = extract_spectrum(spec, scan)
    return spectra


def approximate_scan_map_bytes(spectra: dict[int, dict[str, Any]]) -> int:
    """Rough in-memory footprint for eviction accounting."""
    total = sys.getsizeof(spectra)
    for spec in spectra.values():
        total += sys.getsizeof(spec)
        mz = spec.get("mz") or []
        it = spec.get("intensity") or []
        if isinstance(mz, list):
            total += sys.getsizeof(mz) + len(mz) * 16
        if isinstance(it, list):
            total += sys.getsizeof(it) + len(it) * 16
    return max(total, 4096)
