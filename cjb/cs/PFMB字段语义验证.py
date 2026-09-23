"""PFMB 与 mzML 字段语义验证（数据与语义确认）。

目的：在画图前确认 PFMB 字段含义与 mzML 的关联是否正确，避免"看起来合理、
实际含义错误"的图。覆盖 6 项核对：

  [1] PFMB 质量字段是 neutral mass 还是 m/z
  [2] PFMB intensity 的来源与归一化方式
  [3] obs / theo / ppm / da 的内部一致性
  [4] 是否能取得总峰数 / 未匹配峰 / 总离子强度
  [5] slot_rt 与 mzML RT 的时间单位与时间偏差
  [6] 抽取若干 match，比较 apex slot 与 mzML 最近扫描

运行（在 e:/viewer/back 下，需 DB 在线 + mzML 可访问）：
    $env:PYTHONPATH="."; uv run python ../cs/PFMB字段语义验证.py

可选环境变量：
    VIEWER_PFMB_RESULTS  results.pfmb 路径
    VIEWER_BU_SLUG       数据集 slug（默认 bu_pr1_dia）
    VIEWER_SKIP_MZML=1   跳过 [5]/[6] 的 mzML 比对（仅跑 [1]-[4]）
"""

from __future__ import annotations

import os
import statistics
import sys
from pathlib import Path

from pyteomics import mass
from sqlalchemy import text

from app.bu.deps import require_bu_dataset, require_bu_match
from app.bu.services import spectrum_facade
from app.bu.services.scan_resolver import resolve_ms2_scan_at_rt
from app.core.db import SessionLocal
from app.pfmb import PfmbAnnotationReader

PROTON = 1.007276466812
SLUG = os.environ.get("VIEWER_BU_SLUG", "bu_pr1_dia")
SKIP_MZML = os.environ.get("VIEWER_SKIP_MZML") == "1"
PFMB_PATH = Path(
    os.environ.get(
        "VIEWER_PFMB_RESULTS",
        Path(__file__).resolve().parents[1]
        / "dia-ms2-pipei"
        / "Hela_DIA_v2_for_frontend"
        / "data"
        / "results.pfmb",
    )
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "[OK]" if ok else "[NG]"
    print(f"  {mark} {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def neutral_by(seq: str, ion_type: str, ordinal: int) -> float:
    """无修饰肽段的 b/y 碎片中性单同位素质量（= 单电荷 m/z - 质子）。"""
    frag = seq[:ordinal] if ion_type == "b" else seq[-ordinal:]
    return float(mass.fast_mass(frag, ion_type=ion_type, charge=1)) - PROTON


def check_mass_semantics(reader: PfmbAnnotationReader) -> None:
    print("\n=== [1] 质量字段 = neutral mass 还是 m/z ===")
    max_d_neutral = 0.0
    min_abs_d_mz = 1e9
    checked = 0
    idx = 0
    while checked < 5 and idx < 2000:
        ann = reader.read(idx)
        idx += 1
        if not ann.peptide.isalpha():  # 跳过含修饰括号的肽段
            continue
        for ion in ann.matched_ions:
            if ion.ion_type not in ("b", "y"):
                continue
            theo_neutral = neutral_by(ann.peptide, ion.ion_type, ion.fragment_ordinal)
            max_d_neutral = max(max_d_neutral, abs(ion.theoretical_neutral_mass - theo_neutral))
            min_abs_d_mz = min(min_abs_d_mz, abs(ion.theoretical_neutral_mass - (theo_neutral + PROTON)))
        checked += 1
    print(f"      已核对 {checked} 条无修饰记录的全部 b/y 离子")
    check("PFMB.theo 与计算的中性质量一致 (|Δ|<1e-3 Da)", max_d_neutral < 1e-3, f"max|Δneutral|={max_d_neutral:.6f} Da")
    check("PFMB.theo 不是单电荷 m/z (与 m/z 至少差 ~1 质子)", min_abs_d_mz > 0.9, f"min|Δm/z|={min_abs_d_mz:.5f} Da")
    print("      结论：质量字段为【中性单同位素质量】；画 m/z 谱需用 (neutral + z*proton)/z 换算。")


def check_intensity(reader: PfmbAnnotationReader) -> None:
    print("\n=== [2] intensity 来源与归一化 ===")
    sample = [0, 1, 16, 1000, 50000, 200000, 500000, 800000]
    global_max = 0.0
    total_ions = 0
    zero_ions = 0
    for idx in sample:
        ann = reader.read(idx)
        for ion in ann.matched_ions:
            global_max = max(global_max, ion.intensity)
            total_ions += 1
            if ion.intensity == 0:
                zero_ions += 1
    zero_ratio = zero_ions / total_ions if total_ions else 0
    print(f"      样本离子 {total_ions} 个，全局 max intensity={global_max:.1f}")
    check("非 0-1 归一化 (max > 1)", global_max > 1.0, f"max={global_max:.1f}")
    check("非百分比归一化 (max != 100)", abs(global_max - 100.0) > 1e-6)
    print(f"      ★ intensity==0 的离子占比 = {zero_ratio:.2%}（{zero_ions}/{total_ions}）")
    print("      来源：去卷积后的峰强度（pfm.py: all_peak_intensity[peak]）。未归一化。")
    print("      ★ 注意：相当比例匹配离子 intensity=0，做强度图/总强度时不能当作真实强度直接求和。")


def check_internal_consistency(reader: PfmbAnnotationReader) -> None:
    print("\n=== [3] obs / theo / ppm / da 内部一致性 ===")
    neutron = 1.0033548  # C13-C12 质量差
    max_resid_after = 0.0
    max_d_ppm = 0.0
    iso_offset = 0
    total = 0
    for idx in range(0, 800001, 137):
        ann = reader.read(idx)
        for ion in ann.matched_ions:
            if not ion.theoretical_neutral_mass:
                continue
            total += 1
            calc_ppm = ion.mass_error_da / ion.theoretical_neutral_mass * 1e6
            max_d_ppm = max(max_d_ppm, abs(ion.mass_error_ppm - calc_ppm))
            # obs = theo + da + k*neutron （k 为同位素偏移），去掉整数同位素后残差应≈0
            resid = ion.observed_neutral_mass - ion.theoretical_neutral_mass - ion.mass_error_da
            k = round(resid / neutron)
            if k != 0:
                iso_offset += 1
            max_resid_after = max(max_resid_after, abs(resid - k * neutron))
    print(f"      已扫描 {total} 个匹配离子")
    check("ppm ≈ da/theo*1e6（ppm 与 da 互洽）", max_d_ppm < 0.05, f"max|Δppm|={max_d_ppm:.4f}")
    check(
        "obs = theo + da + k·中子（去同位素后残差<1e-3 Da）",
        max_resid_after < 1e-3,
        f"max残差={max_resid_after:.6f} Da",
    )
    print(f"      ★ 同位素峰（k=±1，obs 比单同位素差约 1 Da）占比 = {iso_offset/total:.2%}（{iso_offset}/{total}）")
    print("      ★ ppm/da 是【已做同位素校正】的真实误差；切勿用 (obs - theo) 反算 ppm，"
          "否则约 1.75% 的离子会出现 ±900 ppm 假误差。")


def check_peak_totals(reader: PfmbAnnotationReader) -> None:
    print("\n=== [4] 总峰数 / 未匹配峰 / 总离子强度 ===")
    ann = reader.read(0)
    distinct_peaks = len({i.peak_id for i in ann.matched_ions})
    print(f"      单条记录字段：仅有 matched_ions（{len(ann.matched_ions)} 个），matched_peak_count={ann.matched_peak_count}")
    check("matched_peak_count == 不重复 peak_id 数", ann.matched_peak_count == distinct_peaks, f"{ann.matched_peak_count} vs {distinct_peaks}")
    summary = PFMB_PATH.parent / "summary_eval.json"
    print(f"      ★ 单条记录【没有】总峰数 / 未匹配峰；这些只在全局 {summary.name} 中：")
    if summary.exists():
        import json

        s = json.loads(summary.read_text(encoding="utf-8"))
        print(f"        total_peaks={s['counts']['total_peaks']}  total_matched_peaks={s['counts']['total_matched_peaks']}")
    print("      ★ 总离子强度只能对 matched_ions 求和（且含 0 强度项），非该 scan 的真实 TIC。")
    print("      ★ mzML scan 的总峰数与 PFMB 是两套峰（mzML 原始质心 vs TopPIC 去卷积峰），不可直接比较。")


def check_time_units(reader: PfmbAnnotationReader, session, dataset) -> None:
    print("\n=== [5][6] slot_rt 与 mzML RT 单位 / 时间偏差 / apex vs 最近扫描 ===")
    dataset_id = int(dataset["dataset_id"])

    if SKIP_MZML:
        print("      VIEWER_SKIP_MZML=1，跳过 mzML 比对。")
        return

    sample_ids = session.execute(
        text(
            "SELECT match_id, run_id FROM identification_matches "
            "WHERE dataset_id = :d AND extra_metadata ? 'pfmb' "
            "ORDER BY match_id LIMIT 12"
        ),
        {"d": dataset_id},
    ).fetchall()

    # 一次性加载 mzML（约 70s）。
    run_id = int(sample_ids[0][1])
    print(f"      加载 mzML run_id={run_id} 的谱图（约 1 分钟）...")
    spectra = spectrum_facade.get_run_spectra(session, dataset_id, run_id)
    ms2_rts = sorted(float(s["rt_seconds"]) for s in spectra.values() if int(s.get("ms_level") or 1) == 2 and s.get("rt_seconds") is not None)
    print(f"      mzML MS2 scan {len(ms2_rts)} 个，rt_seconds 范围 {ms2_rts[0]:.1f}..{ms2_rts[-1]:.1f}")

    # slot_rt 单位确认：apex slot_rt 应落在 mzML 秒级 RT 范围内。
    sample_match = require_bu_match(session, dataset_id, int(sample_ids[0][0]))
    apex_rt0 = _apex_slot_rt(sample_match)
    check(
        "slot_rt 单位 = 秒（落在 mzML rt_seconds 范围内）",
        apex_rt0 is not None and ms2_rts[0] <= apex_rt0 <= ms2_rts[-1],
        f"apex_slot_rt={apex_rt0:.1f}s",
    )

    d_slot_diann: list[float] = []
    d_slot_mzml: list[float] = []
    d_diann_mzml: list[float] = []
    rows_out: list[str] = []
    for match_id, _run in sample_ids:
        m = require_bu_match(session, dataset_id, int(match_id))
        apex_rt = _apex_slot_rt(m)  # 秒
        diann_rt_min = m.get("retention_time")
        if apex_rt is None or diann_rt_min is None:
            continue
        diann_rt = float(diann_rt_min) * 60.0  # 分钟 -> 秒
        try:
            scan = resolve_ms2_scan_at_rt(m, spectra, apex_rt / 60.0)
            mzml_rt = float(spectra[scan]["rt_seconds"])
        except Exception:  # noqa: BLE001
            rows_out.append(f"      match {match_id}: apex={apex_rt:.1f}s diann={diann_rt:.1f}s mzML=无窗口内扫描")
            continue
        d_slot_diann.append(abs(apex_rt - diann_rt))
        d_slot_mzml.append(abs(apex_rt - mzml_rt))
        d_diann_mzml.append(abs(diann_rt - mzml_rt))
        rows_out.append(
            f"      match {match_id}: apex_slot={apex_rt:.1f}s  diann={diann_rt:.1f}s  "
            f"mzML_scan#{scan}={mzml_rt:.1f}s  |apex-diann|={abs(apex_rt-diann_rt):.1f}s  "
            f"|apex-mzML|={abs(apex_rt-mzml_rt):.1f}s"
        )
    for line in rows_out:
        print(line)

    if d_slot_mzml:
        print(
            f"\n      偏差汇总（{len(d_slot_mzml)} 条命中）："
            f"\n        |apex_slot - diann|  中位={statistics.median(d_slot_diann):.2f}s 最大={max(d_slot_diann):.2f}s"
            f"\n        |apex_slot - mzML扫描| 中位={statistics.median(d_slot_mzml):.2f}s 最大={max(d_slot_mzml):.2f}s"
            f"\n        |diann - mzML扫描|    中位={statistics.median(d_diann_mzml):.2f}s 最大={max(d_diann_mzml):.2f}s"
        )
        check("apex_slot 与 mzML 最近扫描偏差 < 10s（中位）", statistics.median(d_slot_mzml) < 10.0)


def _apex_slot_rt(match: dict) -> float | None:
    block = (match.get("extra_metadata") or {}).get("pfmb")
    if not block:
        return None
    slots = block.get("slots", [])
    apex = block.get("apex_slot")
    for s in slots:
        if s.get("slot_index") == apex:
            return float(s["slot_rt"])
    return float(slots[len(slots) // 2]["slot_rt"]) if slots else None


def main() -> int:
    print(f"=== results.pfmb: {PFMB_PATH} ===")
    print(f"=== dataset slug: {SLUG} ===")
    reader = PfmbAnnotationReader(PFMB_PATH)
    check_mass_semantics(reader)
    check_intensity(reader)
    check_internal_consistency(reader)
    check_peak_totals(reader)

    session = SessionLocal()
    try:
        dataset = require_bu_dataset(session, SLUG)
        check_time_units(reader, session, dataset)
    finally:
        session.close()

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项硬校验未通过: {failures}")
        return 1
    print("  [PASS] 所有硬校验通过（语义记录见 cs/PFMB字段语义说明.md）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
