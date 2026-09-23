#!/usr/bin/env python3
"""调用正式 reader 对 DIA-CLIP 数据目录执行只读能力验收。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "back"))

from app.ingest.bu.diaclip_result_reader import prepare_diaclip_source  # noqa: E402


def _required_root() -> Path:
    raw = os.environ.get("VIEWER_DIACLIP_DATASET_ROOT", "").strip()
    if not raw:
        raise SystemExit("请先设置 VIEWER_DIACLIP_DATASET_ROOT 指向待验收的 DIA-CLIP 数据目录。")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"目录不存在或不是文件夹：{root}")
    return root


def _optional_expected(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是整数。") from exc
    if value < 0:
        raise SystemExit(f"{name} 不能为负数。")
    return value


def main() -> None:
    root = _required_root()
    started = time.perf_counter()
    prepared = prepare_diaclip_source(root)
    elapsed = time.perf_counter() - started
    stats = prepared.stats

    checks = {
        "VIEWER_DIACLIP_EXPECTED_TOTAL_ROWS": stats.tsv_total_rows,
        "VIEWER_DIACLIP_EXPECTED_UNIQUE_CANDIDATES": stats.unique_candidates,
        "VIEWER_DIACLIP_EXPECTED_ACCEPTED_TARGETS": stats.accepted_targets,
    }
    failures: list[str] = []
    for env_name, actual in checks.items():
        expected = _optional_expected(env_name)
        if expected is not None and actual != expected:
            failures.append(f"{env_name}: expected={expected}, actual={actual}")

    if prepared.source.software != "DIA-CLIP":
        failures.append(f"software expected=DIA-CLIP, actual={prepared.source.software}")
    if len(prepared.source.identifications) != stats.accepted_targets:
        failures.append(
            "identification count does not equal accepted target count: "
            f"{len(prepared.source.identifications)} != {stats.accepted_targets}"
        )

    print(f"root={root}")
    print(f"result_tsv={prepared.bundle.result_path}")
    print(f"all_report={prepared.bundle.report_path}")
    print(f"run_names={prepared.bundle.report_info.run_names}")
    print(f"tsv_total_rows={stats.tsv_total_rows}")
    print(f"unique_candidates={stats.unique_candidates}")
    print(f"duplicate_rows_removed={stats.duplicate_rows_removed}")
    print(f"target_candidates={stats.target_candidates}")
    print(f"decoy_candidates={stats.decoy_candidates}")
    print(f"accepted_targets={stats.accepted_targets}")
    print(f"q_value_cutoff={stats.q_value_cutoff}")
    print(f"fdr_method={stats.fdr_method}")
    print(f"elapsed_seconds={elapsed:.3f}")

    if failures:
        print("验收失败：", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)
    print("验收通过。")


if __name__ == "__main__":
    main()

