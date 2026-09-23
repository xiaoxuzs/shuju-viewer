#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""
能力测验：对基准数据集目录计算元数据指纹，输出耗时与中位数。

直接运行本文件（在仓库根目录 `viewer` 下）::

    python cs\\指纹性能测验.py

或使用 back 环境::

    uv run --directory back python ..\\cs\\指纹性能测验.py

**请先在本文件顶部修改 `BENCHMARK_DATASET_PATH`**（可填外层嵌套目录，会经
`resolve_ingest_root` 解析）。若同时设置了环境变量 `VIEWER_BENCH_DATASET_ROOT`，
则以环境变量为准（便于 CI 覆盖）。
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

# =============================================================================
# 在下面改路径（必填其一：填常量，或运行前设置环境变量覆盖）
# =============================================================================

# 示例：外层包一层或直指 ingest 根均可
BENCHMARK_DATASET_PATH: str = r"E:\viewer\shuju\MZ20160222DS_histone49_html\MZ20160222DS_histone49_html"

# 中位数耗时上限（秒），可按机器改
TIME_BUDGET_SECONDS: float = 0.5

# 重复测量次数
RUN_COUNT: int = 3

# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "back"))

from app.dataset_ingest_root import resolve_ingest_root  # noqa: E402
from app.fingerprint import compute_dataset_metadata_fingerprint  # noqa: E402


def _resolve_raw_path() -> str:
    env = os.environ.get("VIEWER_BENCH_DATASET_ROOT", "").strip()
    if env:
        return env
    if BENCHMARK_DATASET_PATH.strip():
        return BENCHMARK_DATASET_PATH.strip()
    print(
        "错误：未配置路径。\n"
        "  1）编辑本文件顶部的 BENCHMARK_DATASET_PATH；或\n"
        "  2）设置环境变量 VIEWER_BENCH_DATASET_ROOT。",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    raw = _resolve_raw_path()
    ingest_root = resolve_ingest_root(Path(raw))

    times: list[float] = []
    last_fp = ""
    last_count = 0
    for i in range(RUN_COUNT):
        t0 = time.perf_counter()
        r = compute_dataset_metadata_fingerprint(ingest_root, on_progress=None)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        last_fp = r.fingerprint
        last_count = r.file_count
        print(f"第 {i + 1} 次: {elapsed:.4f}s  file_count={r.file_count}  digest={r.fingerprint}")

    med = statistics.median(times)
    print(f"中位数: {med:.4f}s  (目标 ≤ {TIME_BUDGET_SECONDS}s)")
    print(f"ingest_root: {ingest_root}")
    print(f"原始配置: {raw!r}")

    if med > TIME_BUDGET_SECONDS:
        print(
            f"未达标：中位数 {med:.4f}s 超过 TIME_BUDGET_SECONDS={TIME_BUDGET_SECONDS}。"
            "可在本文件顶部调大 TIME_BUDGET_SECONDS，或优化磁盘/实现。",
            file=sys.stderr,
        )
        sys.exit(1)
    print("达标。")
    _ = last_fp
    _ = last_count


if __name__ == "__main__":
    main()
