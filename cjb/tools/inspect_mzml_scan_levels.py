"""Print read-only scan-level summary for an mzML scan index or mzML file."""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


FIELDS = (
    "scan_number",
    "ms_level",
    "retention_time",
    "tic",
    "bpc",
    "precursor_mz",
)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _load_from_scan_index(path: Path) -> dict[str, np.ndarray]:
    scan_index_path = path / "scan-index-v1.npz" if path.is_dir() else path
    if not scan_index_path.is_file():
        raise FileNotFoundError(f"scan index not found: {scan_index_path}")
    with np.load(scan_index_path, allow_pickle=False) as arrays:
        missing = [field for field in FIELDS if field not in arrays]
        if missing:
            raise ValueError(f"scan index missing fields: {', '.join(missing)}")
        return {field: arrays[field].copy() for field in FIELDS}


def _load_from_mzml(path: Path) -> dict[str, np.ndarray]:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "back"))
    from app.services.mzml_scan_index import generate_scan_index_from_mzml

    index = generate_scan_index_from_mzml(path)
    return {field: getattr(index, field) for field in FIELDS}


def _range(values: np.ndarray) -> tuple[float | None, float | None]:
    finite = [_finite(value) for value in values]
    finite = [value for value in finite if value is not None]
    return (min(finite), max(finite)) if finite else (None, None)


def _consecutive_blocks(levels: list[int], target: int) -> tuple[int, int]:
    count = 0
    longest = 0
    current = 0
    for level in levels:
        if level == target:
            current += 1
            if current == 1:
                count += 1
            longest = max(longest, current)
        else:
            current = 0
    return count, longest


def _ms2_after_ms1(levels: list[int]) -> tuple[float | None, int]:
    buckets: list[int] = []
    current: int | None = None
    for level in levels:
        if level == 1:
            if current is not None:
                buckets.append(current)
            current = 0
        elif level == 2 and current is not None:
            current += 1
    if current is not None:
        buckets.append(current)
    if not buckets:
        return None, 0
    return sum(buckets) / len(buckets), max(buckets)


def _format_number(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def print_summary(data: dict[str, np.ndarray], source: Path) -> None:
    order = np.argsort(data["scan_number"])
    scan_numbers = data["scan_number"][order]
    levels = [int(value) for value in data["ms_level"][order]]
    counts = Counter(levels)
    total = len(levels)
    ms1 = counts.get(1, 0)
    ms2 = counts.get(2, 0)
    other = total - ms1 - ms2
    rt_min, rt_max = _range(data["retention_time"])
    tic_max = _range(data["tic"])[1]
    bpc_max = _range(data["bpc"])[1]
    precursor_linked = sum(
        1
        for level, precursor_mz in zip(levels, data["precursor_mz"][order])
        if level == 2 and _finite(precursor_mz) is not None
    )
    ms1_blocks, longest_ms1 = _consecutive_blocks(levels, 1)
    ms2_blocks, longest_ms2 = _consecutive_blocks(levels, 2)
    avg_ms2_after_ms1, max_ms2_after_ms1 = _ms2_after_ms1(levels)

    print("# mzML scan-level summary")
    print()
    print(f"- Source: `{source}`")
    print(f"- Total scans: {total}")
    print(f"- MS1 scans: {ms1}")
    print(f"- MS2 scans: {ms2}")
    print(f"- Other scans: {other}")
    print(f"- MS level counts: {dict(sorted(counts.items()))}")
    print(f"- RT range: {_format_number(rt_min)}-{_format_number(rt_max)} min")
    if total:
        print(f"- Scan range: {int(scan_numbers.min())}-{int(scan_numbers.max())}")
    else:
        print("- Scan range: -")
    print(f"- Max TIC: {_format_number(tic_max)}")
    print(f"- Max BPC: {_format_number(bpc_max)}")
    print(f"- MS1/MS2 ratio: {_format_number(ms1 / ms2) if ms2 else '-'}")
    print(f"- MS2 fraction: {_format_number(ms2 / total) if total else '-'}")
    print(f"- Precursor-linked MS2 scans: {precursor_linked}")
    print(f"- MS1 blocks: {ms1_blocks} blocks, longest {longest_ms1} scans")
    print(f"- MS2 blocks: {ms2_blocks} blocks, longest {longest_ms2} scans")
    print(
        "- MS2 after each MS1: "
        f"average {_format_number(avg_ms2_after_ms1)}, max {max_ms2_after_ms1}"
    )
    print(f"- First 30 scan levels: {' '.join(f'MS{level}' for level in levels[:30])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scan-index", type=Path, help="Path to scan-index-v1.npz or its directory.")
    source.add_argument("--mzml", type=Path, help="Path to an mzML file. This reads the mzML but writes nothing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.scan_index is not None:
            source = args.scan_index
            data = _load_from_scan_index(source)
        else:
            source = args.mzml
            data = _load_from_mzml(source)
        print_summary(data, source)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
