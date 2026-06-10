"""
Step 1 验证脚本 v2 — 精确定位 parquet 与 pos.pkl 的对应关系。

运行方式（在 e:/viewer/back 下）：
    uv run python ../cs/step1_verify_mapping.py

要点：
  - index.json 的 peptide 字段是 Modified.Sequence（含 C[+57.021464] 等修饰）
  - parquet 用 Stripped.Sequence（纯氨基酸字母）
  - 比较前需对 index.json peptide 去修饰
  - 逐行扫描找第一个真正不一致的位置
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

PARQUET_PATH   = Path(r"d:\dia-shuju\DIANN_2.0\DIANN_2.0\all_report.parquet")
INDEX_JSON_PATH= Path(r"e:\viewer\dia-ms2-pipei\Hela_DIA_v2_for_frontend\data\index.json")
EXPECTED_ROWS  = 110024
Q_CUTOFF       = 0.01
CHECK_FIRST_N  = 25
SAMPLE_ROWS    = [100, 500, 1000, 5000, 10000, 50000, 100000, 109000]
MOD_PATTERN    = re.compile(r"\[.*?\]")   # 去除 [+57.021464] 等修饰标注


def strip_mods(seq: str) -> str:
    """把 'AAAAC[+57.021464]LDK' 转成 'AAAACLDK'。"""
    return MOD_PATTERN.sub("", seq)


# ── 1. 读 index.json，建 source_row → (stripped_peptide, charge) ────────────
print("=== [1/4] 读取 index.json ===")
source_row_map: dict[int, tuple[str, int]] = {}
with open(INDEX_JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)
for item in data["items"]:
    sr = item["source_row"]
    if sr not in source_row_map:
        source_row_map[sr] = (strip_mods(item["peptide"]), item["precursor_charge"])

max_sr = max(source_row_map)
print(f"  source_row 总数: {len(source_row_map)},  最大值: {max_sr}  (预期 {EXPECTED_ROWS-1})")

# ── 2. 扫描 parquet，过滤后收集 (stripped_seq, charge) ──────────────────────
print("\n=== [2/4] 扫描 parquet ===")
pf = pq.ParquetFile(PARQUET_PATH)
print(f"  总行数（含 decoy）: {pf.metadata.num_rows}")

needed_cols = ["Stripped.Sequence", "Precursor.Charge", "Q.Value", "Decoy"]
available   = set(pf.schema_arrow.names)
cols        = [c for c in needed_cols if c in available]

filtered: list[tuple[str, int]] = []
for batch in pf.iter_batches(columns=cols, batch_size=16384):
    names   = batch.schema.names
    col_idx = {n: i for i, n in enumerate(names)}
    seqs    = batch.column(col_idx["Stripped.Sequence"]).to_pylist()
    charges = batch.column(col_idx["Precursor.Charge"]).to_pylist()
    qvals   = batch.column(col_idx["Q.Value"]).to_pylist()
    decoys  = batch.column(col_idx["Decoy"]).to_pylist() if "Decoy" in col_idx else [0]*batch.num_rows
    for i in range(batch.num_rows):
        q = qvals[i]
        d = decoys[i]
        if q is None or q >= Q_CUTOFF:
            continue
        if d and int(d) != 0:
            continue
        filtered.append((str(seqs[i] or ""), int(charges[i] or 0)))

filtered_count = len(filtered)
print(f"  过滤后行数: {filtered_count}  (预期 {EXPECTED_ROWS},  差 {filtered_count - EXPECTED_ROWS:+d})")

# ── 3. 全量逐行扫描，找第一个真正不一致的行 ───────────────────────────────
print("\n=== [3/4] 全量逐行扫描，查找第一个不一致位置 ===")
first_mismatch: int | None = None
mismatch_count = 0
scan_limit = min(filtered_count, EXPECTED_ROWS)

for sr in range(scan_limit):
    parq_seq, parq_chg = filtered[sr]
    idx_seq, idx_chg   = source_row_map.get(sr, ("?", -1))
    if parq_seq != idx_seq or parq_chg != idx_chg:
        mismatch_count += 1
        if first_mismatch is None:
            first_mismatch = sr
            print(f"  !! 第一个不一致: source_row={sr}")
            print(f"       parquet    : ({parq_seq}, z={parq_chg})")
            print(f"       index.json : ({idx_seq}, z={idx_chg})")
            # 打印前后各 3 行上下文
            print("  ... 上下文 (source_row-3 ~ source_row+3):")
            for ctx in range(max(0, sr-3), min(scan_limit, sr+4)):
                p = filtered[ctx]
                i = source_row_map.get(ctx, ("?", -1))
                mark = " <-- 不一致" if p != i else ""
                print(f"    sr={ctx:>6}: parquet=({p[0][:26]}, z={p[1]})  idx=({i[0][:26]}, z={i[1]}){mark}")
            if mismatch_count >= 3:
                break

if first_mismatch is None:
    print(f"  [OK] 前 {scan_limit} 行全部一致（无修饰差异）")
elif mismatch_count < 10:
    print(f"  共发现 {mismatch_count} 处不一致（在前 {scan_limit} 行中）")
else:
    print(f"  发现大量不一致，停止扫描")

# ── 4. 定点抽样验证 ────────────────────────────────────────────────────────
print(f"\n=== [4/4] 定点抽样 (去修饰后比较) ===")
for sr in [0, 1, 2, 3, 17, 100, 500, 1000, 5000, 10000, 50000, 100000]:
    if sr >= filtered_count or sr not in source_row_map:
        print(f"  -- sr={sr:>6}: 超出范围")
        continue
    parq_seq, parq_chg = filtered[sr]
    idx_seq, idx_chg   = source_row_map[sr]
    match = (parq_seq == idx_seq and parq_chg == idx_chg)
    status = "[OK]" if match else "[NG]"
    print(f"  {status} sr={sr:>6}: parquet=({parq_seq[:28]}, z={parq_chg})  idx=({idx_seq[:28]}, z={idx_chg})")

# ── 5. 差 2 行的原因分析 ────────────────────────────────────────────────────
print("\n=== [5/4] 差 2 行的原因分析 ===")
print(f"  parquet 过滤后: {filtered_count}")
print(f"  pos.pkl 行数  : {EXPECTED_ROWS}")
print(f"  差值          : {filtered_count - EXPECTED_ROWS}")
if filtered_count > EXPECTED_ROWS:
    extra = filtered_count - EXPECTED_ROWS
    print(f"  parquet 多了 {extra} 行 —— pos.pkl 生成时可能跳过了 {extra} 行（manifest skipped_rows=0 应再核实）")
    print("  或者 pos.pkl 使用了更严格的二次过滤（如 label_filter=1）")
    # 尝试用 label_filter=1 等效过滤
    print("  manifest 里有 label_filter=1，尝试检查是否有 Q.Value==0 或完全一样的重复行...")
    dupes = sum(1 for i in range(1, len(filtered)) if filtered[i] == filtered[i-1])
    print(f"  相邻重复 (seq,charge) 对数: {dupes}（可能与跳过逻辑有关）")

# ── 6. 总结 ──────────────────────────────────────────────────────────────────
print("\n=== 总结 ===")
if first_mismatch is None and filtered_count == EXPECTED_ROWS:
    print("  [OK] 方案 A 完全可行：行数一致，顺序完全匹配。")
    print("       导入时 enumerate(iter_filtered_rows()) 写 source_row 即可。")
elif first_mismatch is None and filtered_count != EXPECTED_ROWS:
    print(f"  [注意] 顺序一致（已比较的 {scan_limit} 行均匹配），但行数差 {filtered_count - EXPECTED_ROWS}。")
    print("  需确认差的 2 行是在末尾还是插在中间。")
    print("  若差的行均在末尾 → 方案 A 仍可用，source_row 0..110023 安全。")
else:
    print(f"  [注意] 在 source_row={first_mismatch} 处发现真正的顺序差异。")
    print("  需人工判断是否是修饰标注导致的假 NG，还是真正的行序错位。")
