#!/usr/bin/env python3
"""LC-MS 3D API performance smoke test.

Set dataset/run/locator environment variables, start the backend, then run:

    python cs/LCMS三维性能测验.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def main() -> int:
    dataset_id = _env_int("VIEWER_LCMS_DATASET_ID")
    run_id = _env_int("VIEWER_LCMS_RUN_ID")
    if dataset_id is None or run_id is None:
        print("请先设置 VIEWER_LCMS_DATASET_ID 与 VIEWER_LCMS_RUN_ID。")
        return 2

    base = os.getenv("VIEWER_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
    max_seconds = float(os.getenv("VIEWER_LCMS_MAX_SECONDS", "0.5"))

    params: dict[str, str] = {
        "ms_level": "1",
        "rt_window_seconds": os.getenv("VIEWER_LCMS_RT_WINDOW_SECONDS", "300"),
        "mz_window": os.getenv("VIEWER_LCMS_MZ_WINDOW", "90"),
        "frame_radius": os.getenv("VIEWER_LCMS_FRAME_RADIUS", "18"),
        "rt_bins": os.getenv("VIEWER_LCMS_RT_BINS", "108"),
        "mz_bins": os.getenv("VIEWER_LCMS_MZ_BINS", "180"),
        "max_points": os.getenv("VIEWER_LCMS_MAX_POINTS", "50000"),
    }

    center_scan = _env_int("VIEWER_LCMS_CENTER_SCAN")
    center_spec_id = _env_int("VIEWER_LCMS_CENTER_SPEC_ID")
    precursor_mz = _env_float("VIEWER_LCMS_PRECURSOR_MZ")
    if center_scan is not None:
        params["center_scan"] = str(center_scan)
    if center_spec_id is not None:
        params["center_spec_id"] = str(center_spec_id)
    if precursor_mz is not None:
        params["precursor_mz"] = str(precursor_mz)

    url = (
        f"{base}/datasets/{dataset_id}/runs/{run_id}/lcms-3d?"
        + urllib.parse.urlencode(params)
    )

    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.perf_counter() - started

    meta = payload.get("meta", {})
    print(f"LC-MS 3D API: {elapsed:.3f}s")
    print(f"source={payload.get('source')} frames={meta.get('frameCount')} points={meta.get('returnedPointCount')}")
    print(f"server_generated_ms={meta.get('generatedMs')} mz_window_fallback={meta.get('mzWindowFallback')}")

    if elapsed > max_seconds:
        print(f"未达标：耗时 {elapsed:.3f}s > {max_seconds:.3f}s")
        return 1
    print("达标")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
