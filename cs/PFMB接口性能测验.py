"""PFMB 接口性能测验（测试规划：性能目标）。

性能目标：
  1. 单条 annotation 读取保持 O(1)：随机抽多个 prsm_index，耗时近似常数
     （与 prsm_index 大小/位置无关，不随记录数线性增长）。
  2. 热图矩阵接口一次性返回全部 slot 摘要，服务端只需一次调用即可完成，
     前端无需逐 slot 请求（避免 N+1）。

在后端目录运行（pyproject 设置了 pythonpath="."）：

    cd e:/viewer/back
    $env:PYTHONPATH="."; uv run python ../cs/PFMB接口性能测验.py

可用 VIEWER_BU_SLUG 覆盖数据集 slug（默认 bu_pr1_dia）。
本脚本只做相对量级的健康检查，不设硬性毫秒阈值（不同机器差异大），
但会打印实测耗时，并对「O(1) 离散度」与「单次矩阵调用」做断言。
"""

from __future__ import annotations

import os
import sys
import time
from statistics import median

from sqlalchemy import text

from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import ms2_annotation_svc
from app.core.db import SessionLocal

SLUG = os.environ.get("VIEWER_BU_SLUG", "bu_pr1_dia")
N_SAMPLES = 200

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "[OK]" if ok else "[NG]"
    print(f"  {mark} {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    print(f"=== dataset slug: {SLUG} ===")
    session = SessionLocal()
    try:
        dataset = require_bu_dataset(session, SLUG)
        dataset_id = int(dataset["dataset_id"])

        # 收集一批带 pfmb 的 match，并展开其全部 (match_id, prsm_index)。
        rows = session.execute(
            text(
                "SELECT match_id, extra_metadata->'pfmb'->'slots' AS slots "
                "FROM identification_matches "
                "WHERE dataset_id = :d AND extra_metadata ? 'pfmb' "
                "ORDER BY match_id LIMIT 400"
            ),
            {"d": dataset_id},
        ).all()
        samples: list[tuple[int, int]] = []
        for match_id, slots in rows:
            for slot in slots or []:
                samples.append((int(match_id), int(slot["prsm_index"])))
        check("样本充足", len(samples) >= N_SAMPLES, f"{len(samples)} 个 (match,prsm)")
        if not samples:
            raise SystemExit("没有可用的 PFMB 样本")

        # 预热 reader（首个调用含 mmap/打开文件成本，单独排除）。
        first_match = require_bu_match(session, dataset_id, samples[0][0])
        ms2_annotation_svc.get_annotation(dataset, first_match, samples[0][1])

        print("\n=== [1/2] 单条 annotation O(1) ===")
        match_cache: dict[int, dict] = {}
        timings: list[float] = []
        step = max(1, len(samples) // N_SAMPLES)
        picked = samples[::step][:N_SAMPLES]
        for match_id, prsm in picked:
            m = match_cache.get(match_id)
            if m is None:
                m = require_bu_match(session, dataset_id, match_id)
                match_cache[match_id] = m
            t0 = time.perf_counter()
            ms2_annotation_svc.get_annotation(dataset, m, prsm)
            timings.append((time.perf_counter() - t0) * 1000.0)
        timings.sort()
        med = median(timings)
        p95 = timings[int(len(timings) * 0.95) - 1]
        mx = timings[-1]
        print(f"      n={len(timings)}  median={med:.3f}ms  p95={p95:.3f}ms  max={mx:.3f}ms")
        # O(1) 健康度：p95 不应远超中位数（随机访问，与位置无关）。
        check("O(1)：p95 / median < 8x", p95 < max(med * 8, 1.0), f"p95/median={p95/med if med else 0:.1f}x")

        print("\n=== [2/2] 矩阵接口一次性返回全部 slot（无 N+1）===")
        # 选 slot 最多的 match，统计服务内部读取次数。
        big_match_id = session.execute(
            text(
                "SELECT match_id FROM identification_matches "
                "WHERE dataset_id = :d AND extra_metadata ? 'pfmb' "
                "ORDER BY jsonb_array_length(extra_metadata->'pfmb'->'slots') DESC, match_id LIMIT 1"
            ),
            {"d": dataset_id},
        ).scalar_one()
        big_match = require_bu_match(session, dataset_id, int(big_match_id))
        n_slots = len(ms2_annotation_svc.get_slots(dataset, big_match).slots)

        # 包裹 reader.read 计数：矩阵一次调用内部读取次数 == slot 数（每 slot 恰好读一次）。
        sidecar = ms2_annotation_svc.resolve_sidecar(dataset.get("extra_metadata"))
        reader = ms2_annotation_svc._reader(str(sidecar.pfmb_path))
        original_read = reader.read
        calls = {"n": 0}

        def counting_read(prsm_index: int):
            calls["n"] += 1
            return original_read(prsm_index)

        reader.read = counting_read  # type: ignore[method-assign]
        try:
            t0 = time.perf_counter()
            matrix = ms2_annotation_svc.get_annotation_matrix(dataset, big_match)
            dt = (time.perf_counter() - t0) * 1000.0
        finally:
            reader.read = original_read  # type: ignore[method-assign]

        print(f"      slots={n_slots}  内部 read 次数={calls['n']}  矩阵耗时={dt:.2f}ms")
        check("矩阵内部每 slot 仅读一次（read==slots）", calls["n"] == n_slots, f"{calls['n']} vs {n_slots}")
        check("矩阵返回 slot_summary 覆盖全部 slot", len(matrix.slot_summary) == n_slots, f"{len(matrix.slot_summary)}")
    finally:
        session.close()

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过: {failures}")
        return 1
    print("  [PASS] 性能测验通过（O(1) 单条读取 + 单次矩阵聚合）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
