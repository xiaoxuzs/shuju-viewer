"""验证 RT x Fragment 矩阵接口（第六阶段：ms2-annotation-matrix）。

需要数据库在运行，且数据集已按 --pfmb-sidecar-dir 重新导入。

在后端目录运行（pyproject 设置了 pythonpath="."）：

    cd e:/viewer/back
    $env:PYTHONPATH="."; uv run python ../cs/PFMB矩阵接口验证.py

可用 VIEWER_BU_SLUG 覆盖数据集 slug（默认 bu_pr1_dia）。

验收要点（对应「一次请求完成热图加载，不产生 N+1」）：
  1. get_annotation_matrix 一次性返回全部 slot 列与碎片行；
  2. 矩阵维度 = len(fragments) x len(slots)，为稠密矩阵；
  3. 电荷已合并：同一 (ion_type, fragment_ordinal) 在某 slot 的强度
     等于该 slot 中所有电荷的强度之和（与逐条 get_annotation 聚合一致）；
  4. occurrence/total_intensity 与矩阵单元一致；行按 (occurrence, total) 降序；
  5. apex_slot 与 get_slots 输出一致。
  6. slot_summary.total_intensity 按 distinct peak_id 去重；矩阵仍保留每条
     fragment annotation，存在一峰多注释时矩阵列和可以更大。
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

from sqlalchemy import text

from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import ms2_annotation_svc
from app.core.db import SessionLocal

SLUG = os.environ.get("VIEWER_BU_SLUG", "bu_pr1_dia")

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

        # 选一条 slot 较多的 match，矩阵更有代表性。
        match_id = session.execute(
            text(
                "SELECT match_id FROM identification_matches "
                "WHERE dataset_id = :d AND extra_metadata ? 'pfmb' "
                "ORDER BY jsonb_array_length(extra_metadata->'pfmb'->'slots') DESC, match_id "
                "LIMIT 1"
            ),
            {"d": dataset_id},
        ).scalar_one()
        match = require_bu_match(session, dataset_id, int(match_id))
        print(f"    选用 match_id={match_id}")

        print("\n=== [1/5] 维度与稠密性 ===")
        matrix = ms2_annotation_svc.get_annotation_matrix(dataset, match)
        n_rows = len(matrix.fragments)
        n_cols = len(matrix.slots)
        check("slots 非空", n_cols > 0, f"{n_cols} 列")
        check("fragments 非空", n_rows > 0, f"{n_rows} 行")
        check(
            "intensity 维度 == rows x cols（稠密矩阵）",
            len(matrix.intensity) == n_rows and all(len(r) == n_cols for r in matrix.intensity),
            f"{len(matrix.intensity)} x {len(matrix.intensity[0]) if matrix.intensity else 0}",
        )

        print("\n=== [2/5] 行排序（occurrence 降序, total 降序）===")
        rank = [(-f.occurrence, -f.total_intensity) for f in matrix.fragments]
        check("fragments 已按信息量排序", rank == sorted(rank), f"前3: {[f.key for f in matrix.fragments[:3]]}")

        print("\n=== [3/5] occurrence / total 与单元一致 ===")
        occ_ok = True
        tot_ok = True
        for r, frag in enumerate(matrix.fragments):
            cells = matrix.intensity[r]
            occ = sum(1 for v in cells if v > 0)
            tot = sum(cells)
            if occ != frag.occurrence:
                occ_ok = False
            if abs(tot - frag.total_intensity) > 1e-3:
                tot_ok = False
        check("occurrence == 单元中 >0 的列数", occ_ok)
        check("total_intensity == 单元行和", tot_ok)

        print("\n=== [4/5] 电荷合并：与逐条 get_annotation 聚合一致 ===")
        # 对每个 slot 逐条读取，按 (ion_type, ordinal) 求和，逐 slot 与矩阵比对。
        key_to_row = {f.key: i for i, f in enumerate(matrix.fragments)}
        mismatch = 0
        checked_cells = 0
        for col, slot in enumerate(matrix.slots):
            ann = ms2_annotation_svc.get_annotation(dataset, match, slot.prsm_index)
            agg: dict[str, float] = defaultdict(float)
            for ion in ann.matched_ions:
                agg[f"{ion.ion_type}{ion.fragment_ordinal}"] += ion.intensity
            for key, val in agg.items():
                row = key_to_row.get(key)
                if row is None:
                    mismatch += 1
                    continue
                checked_cells += 1
                if abs(matrix.intensity[row][col] - val) > 1e-3:
                    mismatch += 1
        check("逐 slot 电荷合并强度与矩阵一致", mismatch == 0, f"已比对 {checked_cells} 个单元, 不一致 {mismatch}")

        print("\n=== [5/6] apex_slot 与 get_slots 一致 ===")
        slot_out = ms2_annotation_svc.get_slots(dataset, match)
        check("apex_slot 一致", matrix.apex_slot == slot_out.apex_slot, f"{matrix.apex_slot} vs {slot_out.apex_slot}")
        check("peptide 非空", bool(matrix.peptide), matrix.peptide)
        print(f"      矩阵规模: {n_rows} 碎片 x {n_cols} slot; apex_slot={matrix.apex_slot}")

        print("\n=== [6/6] slot_summary 与逐条 get_annotation 一致 ===")
        check("slot_summary 长度 == slots", len(matrix.slot_summary) == n_cols, f"{len(matrix.slot_summary)}")
        s_align = True
        s_peak = True
        s_int = True
        for col, summ in enumerate(matrix.slot_summary):
            slot = matrix.slots[col]
            if summ.prsm_index != slot.prsm_index or summ.slot_index != slot.slot_index:
                s_align = False
            ann = ms2_annotation_svc.get_annotation(dataset, match, slot.prsm_index)
            if summ.matched_peak_count != ann.matched_peak_count:
                s_peak = False
            if summ.matched_ion_count != len(ann.matched_ions):
                s_peak = False
            by_peak: dict[int, float] = {}
            for ion in ann.matched_ions:
                by_peak[ion.peak_id] = max(by_peak.get(ion.peak_id, 0.0), ion.intensity)
            unique_peak_sum = sum(by_peak.values())
            if abs(summ.total_intensity - unique_peak_sum) > 1e-3:
                s_int = False
        check("slot_summary 与 slots 对齐（prsm/slot_index）", s_align)
        check("matched_peak_count / matched_ion_count 与 get_annotation 一致", s_peak)
        check("slot_summary.total_intensity == distinct peak_id 强度和", s_int)
    finally:
        session.close()

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过: {failures}")
        return 1
    print("  [PASS] ms2-annotation-matrix 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
