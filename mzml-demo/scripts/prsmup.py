"""
prsmup.py — 从 TopPIC prsm.xml + TopFD ms2.msalign 生成与 TopPIC HTML 同形的 prsm*.js

用途（mzml-demo 独立演示）：
  将鉴定结果（XML）与去卷积谱（msalign）合并为前端可用的 ``prsm_data = { ... }``，
  字段布局对齐 ``prsm0.js``；匹配到的 b/y 离子由本脚本重算（见 README）。

用法::

    python scripts/prsmup.py \\
        --prsm-xml  "<...>/toppic/..._toppic_prsm.xml" \\
        --msalign   "<...>/topfd/..._ms2.msalign" \\
        --out-dir   data \\
        --limit     10

说明：生产环境可直接使用 TopPIC 输出的 ``prsms/prsm*.js``；本脚本用于无 HTML 包时的补齐。
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# =============================================================================
# 物理常数与氨基酸单同位素质量表（Da）
# =============================================================================
# 来源：质谱检索通用单同位素表（与 SEQUEST / pyteomics 等一致），非从数据文件读取。
# H2O / PROTON：IUPAC 单同位素原子量加和后的标准值，用于 y 离子末端水与 m/z 换算。
# =============================================================================

AA_MASS: dict[str, float] = {
    "A": 71.03711, "R": 156.10111, "N": 114.04293, "D": 115.02694,
    "C": 103.00919, "E": 129.04259, "Q": 128.05858, "G": 57.02146,
    "H": 137.05891, "I": 113.08406, "L": 113.08406, "K": 128.09496,
    "M": 131.04049, "F": 147.06841, "P": 97.05276, "S": 87.03203,
    "T": 101.04768, "W": 186.07931, "Y": 163.06333, "V": 99.06841,
}
# 中性 H2O 单同位素质量，用于 y 离子 = C 端片段 + H2O
H2O = 18.0105646863
# 质子质量，用于 (M + z*M_p) / z 从中性质量换算 m/z
PROTON = 1.00727646677


# =============================================================================
# TopFD：解析 _ms2.msalign（按 scan 建索引）
# =============================================================================


def parse_msalign(path: Path) -> dict[int, dict[str, Any]]:
    """
    读取 TopFD 输出的 MS2 去卷积谱文本。

    每个谱块以 BEGIN IONS / END IONS 包裹；首行键值对为 SCANS=、PRECURSOR_*= 等；
    数字行 ``mass intensity charge score`` 为去卷积峰（单同位素中性质量，单位 Da）。

    :return: ``{SCANS= 对应的 scan 号: {键值对..., "peaks": [{mass, intensity, charge}, ...]}}``
    """
    out: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    peaks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            if line == "BEGIN IONS":
                current = {}
                peaks = []
                continue
            if line == "END IONS":
                if current is not None:
                    current["peaks"] = peaks
                    scan = current.get("SCANS")
                    if scan:
                        try:
                            out[int(scan)] = current
                        except ValueError:
                            pass
                current = None
                peaks = []
                continue
            if current is None:
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                current[k.strip()] = v.strip()
            else:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        peaks.append({
                            "mass": float(parts[0]),
                            "intensity": float(parts[1]),
                            "charge": int(parts[2]),
                        })
                    except ValueError:
                        pass
    return out


# =============================================================================
# TopPIC：解析 prsm.xml（与 .toppic_raw_prsm 同结构）
# =============================================================================


def parse_prsm_xml(path: Path) -> list[dict[str, Any]]:
    """
    提取每条 <prsm> 的 proteoform、统计量、与谱图关联的 scan 号。

    每条结果含：prsm_id、spectrum_scan（与 msalign 的 SCANS 对齐）、序列、
    mass_shift 列表（left_bp_pos/right_bp_pos/shift）等，供理论离子与写 js 使用。
    """
    tree = ET.parse(path)
    root = tree.getroot()
    entries: list[dict[str, Any]] = []
    for prsm in root.findall("prsm"):
        pf = prsm.find("proteoform")
        if pf is None:
            continue
        shifts: list[dict[str, Any]] = []
        for sh in pf.findall("mass_shift_list/mass_shift"):
            shifts.append({
                "left": int(sh.findtext("left_bp_pos", "0")),
                "right": int(sh.findtext("right_bp_pos", "0")),
                "shift": float(sh.findtext("shift", "0")),
                "type": sh.findtext(
                    "alteration_list/alteration/alter_type/name", "Unexpected"
                ).lower(),
            })
        entries.append({
            "prsm_id": prsm.findtext("prsm_id", "0"),
            "spectrum_id": prsm.findtext("spectrum_id", "0"),
            "spectrum_scan": int(prsm.findtext("spectrum_scan", "0")),
            "p_value": prsm.findtext("extreme_value/p_value", "0"),
            "e_value": prsm.findtext("extreme_value/e_value", "0"),
            "fdr": prsm.findtext("fdr", "-1"),
            "start_pos": int(pf.findtext("start_pos", "0")),
            "end_pos": int(pf.findtext("end_pos", "0")),
            "proteo_db_seq": pf.findtext("proteo_db_seq", ""),
            "proteo_match_seq": pf.findtext("proteo_match_seq", ""),
            "seq_name": pf.findtext("fasta_seq/seq_name", ""),
            "seq_desc": pf.findtext("fasta_seq/seq_desc", ""),
            "n_term_form": pf.findtext("prot_mod/name", "NONE"),
            "mass_shifts": shifts,
        })
    return entries


# =============================================================================
# 理论 b/y 与峰匹配（本脚本“原创”部分，非 TopPIC 导出的明细）
# =============================================================================


def theoretical_by(
    seq: str, mass_shifts: list[dict[str, Any]]
) -> tuple[list[float], list[float]]:
    """
    计算蛋白形式序列上各切割点的理论 b / y 中性单同位素质量（长度各 N-1）。

    mass shift 语义（与 TopPIC 区间 [l, r) 一致）：
      - 对 b_i（N 端 i 个残基）：若某 shift 的 r <= i，整段落在 N 端碎片内，则 b_i += Δ
      - 对 y_i（C 端 i 个残基，代码里 y 下标 j 对应 C 端长度 j+1，见 match_peaks）：
        若某 shift 的 l >= N-i（即整段落在该 y 的 C 端段内），则 y 加 Δ

    注：未实现 N 端 NME/乙酰化对前缀质量的修正（demo 简化），与官方 HTML 可能略有差异。
    """
    n = len(seq)
    prefix = [0.0] * (n + 1)
    for i, aa in enumerate(seq):
        prefix[i + 1] = prefix[i] + AA_MASS.get(aa, 0.0)
    total = prefix[n]

    b: list[float] = []
    y: list[float] = []
    for i in range(1, n):
        bm = prefix[i]
        ym = (total - prefix[i]) + H2O
        for sh in mass_shifts:
            if sh["right"] <= i:
                bm += sh["shift"]
            if sh["left"] >= i:
                ym += sh["shift"]
        b.append(bm)
        y.append(ym)
    return b, y


def match_peaks(
    peaks: list[dict[str, Any]],
    b_list: list[float],
    y_list: list[float],
    tolerance_ppm: float,
) -> dict[int, dict[str, Any]]:
    """
    将每条去卷积峰（中性质量 m）与所有理论 b、y 比较，在 tolerance_ppm 内取 |ppm| 最小的一条。

    :return: ``{峰在 peaks 列表中的下标: {ion_type, ion_position, theoretical_mass, mass_error, ppm}}``
    """
    matches: dict[int, dict[str, Any]] = {}
    for idx, p in enumerate(peaks):
        m = p["mass"]
        best: dict[str, Any] | None = None
        best_err = float("inf")
        for j, bm in enumerate(b_list):
            if bm <= 0:
                continue
            ppm = (m - bm) / bm * 1e6
            if abs(ppm) <= tolerance_ppm and abs(ppm) < best_err:
                best = {"ion_type": "B", "ion_position": j + 1,
                        "theoretical_mass": bm, "mass_error": m - bm, "ppm": ppm}
                best_err = abs(ppm)
        for j, ym in enumerate(y_list):
            if ym <= 0:
                continue
            ppm = (m - ym) / ym * 1e6
            if abs(ppm) <= tolerance_ppm and abs(ppm) < best_err:
                best = {"ion_type": "Y", "ion_position": j + 1,
                        "theoretical_mass": ym, "mass_error": m - ym, "ppm": ppm}
                best_err = abs(ppm)
        if best:
            matches[idx] = best
    return matches


# =============================================================================
# 组装与 TopPIC HTML 同键名的 JSON，并写 ``prsm_data =`` 文件
# =============================================================================


def _fmt_matched_ion(ion: dict[str, Any]) -> dict[str, Any]:
    """把内部 match 字典压成 prsm0.js 里 matched_ion 子对象的字符串字段形式。"""
    pos = int(ion["ion_position"])
    return {
        "ion_type": ion["ion_type"],
        "match_shift": f"{0.0:.10f}",
        "theoretical_mass": f"{ion['theoretical_mass']:.4f}",
        "ion_position": str(pos),
        "ion_display_position": str(pos),
        "ion_sort_name": f"{ion['ion_type']}{pos:05d}",
        "ion_left_position": str(pos),
        "mass_error": f"{ion['mass_error']:.4f}",
        "ppm": f"{ion['ppm']:.2f}",
    }


def build_prsm_js(
    entry: dict[str, Any],
    msa: dict[str, Any],
    matched: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    拼出根键 ``prsm`` 下的完整结构：ms_header、peaks、annotated_protein.annotation。

    cleavage：位置 0..N；在位置 cp 前若存在 B 且 ion_position==cp 则记 N 端命中；
    Y 离子按 C 端长度与切割位置关系映射到 y_by_pos (见循环内 n - pos)。
    """
    seq = entry["proteo_db_seq"]
    n = len(seq)
    spec_id = msa.get("SPECTRUM_ID", "0")

    # 逐条去卷积峰：抄入 msalign，并挂上匹配到的 b/y（若有）
    peaks_out: list[dict[str, Any]] = []
    for idx, p in enumerate(msa["peaks"]):
        charge = p["charge"]
        mass = p["mass"]
        mz = (mass + charge * PROTON) / charge
        obj: dict[str, Any] = {
            "spec_id": str(spec_id),
            "peak_id": str(idx),
            "monoisotopic_mass": f"{mass:.4f}",
            "monoisotopic_mz": f"{mz:.4f}",
            "intensity": f"{p['intensity']:.2f}",
            "charge": str(charge),
        }
        if idx in matched:
            obj["matched_ions_num"] = "1"
            obj["matched_ions"] = {"matched_ion": _fmt_matched_ion(matched[idx])}
        peaks_out.append(obj)

    residues_out = [{"position": str(i), "acid": aa} for i, aa in enumerate(seq)]

    # 按切割位聚类：B@pos 对应 cleavage position = pos；Y@pos 对应 cleavage position = n - pos
    peak_charge_by_id = {str(i): str(p["charge"]) for i, p in enumerate(msa["peaks"])}
    cleavages_out: list[dict[str, Any]] = []
    b_by_pos: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    y_by_pos: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for pid, ion in matched.items():
        pos = int(ion["ion_position"])
        if ion["ion_type"] == "B":
            b_by_pos.setdefault(pos, []).append((pid, ion))
        else:
            y_by_pos.setdefault(n - pos, []).append((pid, ion))

    for cp in range(n + 1):
        n_hits = b_by_pos.get(cp, [])
        c_hits = y_by_pos.get(cp, [])
        all_mp: list[dict[str, Any]] = []
        for pid, ion in n_hits:
            all_mp.append({
                "ion_type": ion["ion_type"],
                "ion_position": str(ion["ion_position"]),
                "ion_display_position": str(ion["ion_position"]),
                "spec_id": str(spec_id),
                "peak_id": str(pid),
                "peak_charge": peak_charge_by_id.get(str(pid), "0"),
            })
        for pid, ion in c_hits:
            all_mp.append({
                "ion_type": ion["ion_type"],
                "ion_position": str(ion["ion_position"]),
                "ion_display_position": str(ion["ion_position"]),
                "spec_id": str(spec_id),
                "peak_id": str(pid),
                "peak_charge": peak_charge_by_id.get(str(pid), "0"),
            })
        cleavages_out.append({
            "position": str(cp),
            "exist_n_ion": "1" if n_hits else "0",
            "exist_c_ion": "1" if c_hits else "0",
            "matched_peaks": (
                None if not all_mp else
                {"matched_peak": all_mp[0] if len(all_mp) == 1 else all_mp}
            ),
        })

    mass_shift_objects = [
        {
            "id": str(index),
            "left_position": str(sh["left"]),
            "right_position": str(sh["right"]),
            "shift": f"{sh['shift']:.10f}",
            "anno": f"{sh['shift']:+.4f}",
            "shift_type": sh.get("type", "unexpected"),
        }
        for index, sh in enumerate(entry["mass_shifts"])
    ]

    annot: dict[str, Any] = {
        "protein_length": str(n),
        "first_residue_position": str(entry["start_pos"]),
        "last_residue_position": str(entry["end_pos"]),
        "annotated_seq": entry["proteo_match_seq"],
        "residue": residues_out,
        "cleavage": cleavages_out,
    }
    if len(mass_shift_objects) == 1:
        # Preserve the existing single-modification JS contract.
        annot["mass_shift"] = mass_shift_objects[0]
    elif mass_shift_objects:
        annot["mass_shift"] = mass_shift_objects

    return {
        "prsm": {
            "prsm_id": str(entry["prsm_id"]),
            "p_value": str(entry.get("p_value", "0")),
            "e_value": str(entry.get("e_value", "0")),
            "fdr": str(entry.get("fdr", "-1")),
            "matched_fragment_number": str(len(matched)),
            "matched_peak_number": str(len(matched)),
            "ms": {
                "ms_header": {
                    "spectrum_file_name": msa.get("FILE_NAME", ""),
                    "ms1_ids": msa.get("MS_ONE_ID", "0"),
                    "ms1_scans": msa.get("MS_ONE_SCAN", "0"),
                    "ids": str(spec_id),
                    "scans": msa.get("SCANS", "0"),
                    "precursor_mono_mass": _ffmt(msa.get("PRECURSOR_MASS")),
                    "precursor_charge": msa.get("PRECURSOR_CHARGE", "0") or "0",
                    "precursor_mz": _ffmt(msa.get("PRECURSOR_MZ")),
                    "feature_inte": msa.get("PRECURSOR_INTENSITY", "0") or "0",
                },
                "peaks": {"peak": peaks_out},
            },
            "annotated_protein": {
                "sequence_id": "0",
                "proteoform_id": str(entry["prsm_id"]),
                "sequence_name": entry["seq_name"],
                "sequence_description": entry["seq_desc"],
                "proteoform_mass": _ffmt(msa.get("PRECURSOR_MASS")),
                "n_acetylation": "1" if "ACETYLATION" in entry["n_term_form"] else "0",
                "unexpected_shift_number": str(len(entry["mass_shifts"])),
                "annotation": annot,
            },
        }
    }


def _ffmt(v: Any) -> str:
    """前体等数值字段统一四位小数字符串；非法则 \"0\"。"""
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prsm-xml", required=True,
                        help="TopPIC *_toppic_prsm.xml (or .toppic_raw_prsm)")
    parser.add_argument("--msalign", required=True,
                        help="TopFD *_ms2.msalign")
    parser.add_argument("--out-dir", required=True,
                        help="输出目录，将写入 prsm<id>.js")
    parser.add_argument("--tolerance-ppm", type=float, default=10.0,
                        help="b/y 与去卷积峰匹配容差（ppm）")
    parser.add_argument("--limit", type=int, default=10,
                        help="按 e_value 从优导出前 N 条 PrSM")
    args = parser.parse_args()

    entries = parse_prsm_xml(Path(args.prsm_xml))
    msalign_map = parse_msalign(Path(args.msalign))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _ev(e: dict[str, Any]) -> float:
        try:
            return float(e["e_value"])
        except Exception:
            return float("inf")

    entries.sort(key=_ev)
    exported = 0
    for e in entries:
        if exported >= args.limit:
            break
        scan = e["spectrum_scan"]
        msa = msalign_map.get(scan)
        if msa is None:
            print(f"[skip] scan {scan} not in msalign")
            continue
        b_list, y_list = theoretical_by(e["proteo_db_seq"], e["mass_shifts"])
        matched = match_peaks(msa["peaks"], b_list, y_list, args.tolerance_ppm)
        prsm_js = build_prsm_js(e, msa, matched)
        body = "prsm_data =\n" + json.dumps(prsm_js, indent=4, ensure_ascii=False) + "\n"
        out_path = out_dir / f"prsm{e['prsm_id']}.js"
        out_path.write_text(body, encoding="utf-8")
        print(f"[ok] wrote {out_path.name}  (scan={scan}, protein={e['seq_name']}, matched={len(matched)})")
        exported += 1

    print(f"done: {exported} file(s) in {out_dir}")


if __name__ == "__main__":
    main()
