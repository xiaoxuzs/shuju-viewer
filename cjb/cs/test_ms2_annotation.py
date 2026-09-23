"""End-to-end verification for the PFMB MS2 annotation service (Step 4+3).

Requires the DB to be running and the dataset re-imported with --pfmb-sidecar-dir.

Run from the backend (pyproject sets pythonpath="."):

    cd e:/viewer/back
    $env:PYTHONPATH="."; uv run python ../cs/test_ms2_annotation.py

Override the dataset slug with VIEWER_BU_SLUG (default: bu_pr1_dia).

Checks:
  1. dataset.capabilities.has_ms2_pfmb is True; extra.ms2_annotation resolves;
  2. a meaningful share of matches got a baked pfmb block;
  3. get_slots returns ordered RT slots with has_pfmb=True;
  4. get_annotation reads real PFMB ions (b/y/c/z_dot), restricted to the match;
  5. a foreign prsm_index is rejected (404).
"""

from __future__ import annotations

import os
import sys

from fastapi import HTTPException
from sqlalchemy import text

from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import ms2_annotation_svc
from app.core.db import SessionLocal
from app.pfmb.locator import resolve_sidecar

SLUG = os.environ.get("VIEWER_BU_SLUG", "bu_pr1_dia")
ALLOWED_SERIES = {"b", "y", "c", "z_dot"}

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

        print("\n=== [1/5] capabilities + sidecar ===")
        caps = dataset.get("capabilities") or {}
        check("capabilities.has_ms2_pfmb == True", caps.get("has_ms2_pfmb") is True, f"{caps.get('has_ms2_pfmb')}")
        sidecar = resolve_sidecar(dataset.get("extra_metadata"))
        check("extra.ms2_annotation 解析到存在的文件", sidecar is not None, str(sidecar))

        print("\n=== [2/5] 每条 match 的 pfmb 烤入率 ===")
        total = session.execute(
            text("SELECT count(*) FROM identification_matches WHERE dataset_id = :d"),
            {"d": dataset_id},
        ).scalar_one()
        with_pfmb = session.execute(
            text(
                "SELECT count(*) FROM identification_matches "
                "WHERE dataset_id = :d AND extra_metadata ? 'pfmb'"
            ),
            {"d": dataset_id},
        ).scalar_one()
        ratio = with_pfmb / total if total else 0
        print(f"      total={total}  with_pfmb={with_pfmb}  ratio={ratio:.4f}")
        check("烤入率 > 0.95", ratio > 0.95, f"{ratio:.4f}")

        print("\n=== [3/5] get_slots ===")
        match_id = session.execute(
            text(
                "SELECT match_id FROM identification_matches "
                "WHERE dataset_id = :d AND extra_metadata ? 'pfmb' ORDER BY match_id LIMIT 1"
            ),
            {"d": dataset_id},
        ).scalar_one()
        match = require_bu_match(session, dataset_id, int(match_id))
        slot_out = ms2_annotation_svc.get_slots(dataset, match)
        check("has_pfmb == True", slot_out.has_pfmb is True)
        check("slots 非空", len(slot_out.slots) > 0, f"{len(slot_out.slots)} 个 (source_row={slot_out.source_row})")
        idxs = [s.slot_index for s in slot_out.slots]
        check("slots 按 slot_index 升序", idxs == sorted(idxs))
        for s in slot_out.slots[:4]:
            print(f"      prsm={s.prsm_index} slot={s.slot_index} rt={s.rt_minutes:.2f}min ({s.slot_rt_seconds:.1f}s)")

        print("\n=== [4/5] get_annotation ===")
        prsm = slot_out.slots[0].prsm_index
        ann = ms2_annotation_svc.get_annotation(dataset, match, prsm)
        check("prsm_index 一致", ann.prsm_index == prsm, f"{ann.prsm_index}")
        check("matched_ions 非空", len(ann.matched_ions) > 0, f"{len(ann.matched_ions)} 个")
        series = {i.ion_type for i in ann.matched_ions}
        check("ion_type 都在 {b,y,c,z_dot}", series <= ALLOWED_SERIES, f"{series}")
        print(f"      peptide={ann.peptide} matched_peak_count={ann.matched_peak_count}")
        for i in ann.matched_ions[:5]:
            print(f"      {i.ion_type}{i.fragment_ordinal} z={i.charge} ppm={i.mass_error_ppm:.3f} da={i.mass_error_da:.4f}")

        print("\n=== [5/5] 越界 prsm_index 拒绝 ===")
        foreign = max(s.prsm_index for s in slot_out.slots) + 10_000_000
        try:
            ms2_annotation_svc.get_annotation(dataset, match, foreign)
            check("外部 prsm_index 应 404", False, "未抛异常")
        except HTTPException as exc:
            check("外部 prsm_index -> 404", exc.status_code == 404, f"status={exc.status_code} detail={exc.detail}")
    finally:
        session.close()

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过: {failures}")
        return 1
    print("  [PASS] ms2_annotation 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
