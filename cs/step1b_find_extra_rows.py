"""
Step 1b v2 — 双指针精确找出 parquet 比 pos.pkl 多出的 2 行。

算法：
  - 同步遍历 parquet_filtered[] 和 pkl_ordered[]
  - 遇到不一致时向前看：若 parquet[i+1] == pkl[j] → parquet[i] 是额外行
  - 记录所有额外行，验证总数 == 2
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pyarrow.parquet as pq

PARQUET_PATH    = Path(r"d:\dia-shuju\DIANN_2.0\DIANN_2.0\all_report.parquet")
INDEX_JSON_PATH = Path(r"e:\viewer\dia-ms2-pipei\Hela_DIA_v2_for_frontend\data\index.json")
Q_CUTOFF        = 0.01
MOD_RE          = re.compile(r"\[.*?\]")

def strip_mods(s: str) -> str:
    return MOD_RE.sub("", s)

# ── 1. 读 index.json: source_row → (stripped_seq, charge) ─────────────────
print("=== [1/3] 读取 index.json ===")
idx_first: dict[int, tuple[str, int]] = {}
with open(INDEX_JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)
for item in data["items"]:
    sr = item["source_row"]
    if sr not in idx_first:
        idx_first[sr] = (strip_mods(item["peptide"]), item["precursor_charge"])

pkl: list[tuple[str, int]] = [idx_first[i] for i in range(max(idx_first)+1)]
print(f"  pos.pkl 行数: {len(pkl)}")

# ── 2. 扫描 parquet，收集过滤后全量 ────────────────────────────────────────
print("\n=== [2/3] 扫描 parquet (全量读入) ===")
pf   = pq.ParquetFile(PARQUET_PATH)
needed = ["Stripped.Sequence", "Precursor.Charge", "Q.Value", "Decoy"]
avail  = set(pf.schema_arrow.names)
cols   = [c for c in needed if c in avail]

parq: list[tuple[str, int]] = []
for batch in pf.iter_batches(columns=cols, batch_size=32768):
    names   = batch.schema.names
    ci      = {n: i for i, n in enumerate(names)}
    seqs    = batch.column(ci["Stripped.Sequence"]).to_pylist()
    charges = batch.column(ci["Precursor.Charge"]).to_pylist()
    qvals   = batch.column(ci["Q.Value"]).to_pylist()
    decoys  = batch.column(ci["Decoy"]).to_pylist() if "Decoy" in ci else [0]*batch.num_rows
    for i in range(batch.num_rows):
        q = qvals[i]
        d = decoys[i]
        if q is None or q >= Q_CUTOFF:
            continue
        if d and int(d) != 0:
            continue
        parq.append((str(seqs[i] or ""), int(charges[i] or 0)))

print(f"  parquet 过滤后行数: {len(parq)}  (pos.pkl={len(pkl)},  差={len(parq)-len(pkl):+d})")

# ── 3. 双指针找额外行 ────────────────────────────────────────────────────────
print("\n=== [3/3] 双指针对比 ===")
extra_parq_rows: list[tuple[int, tuple[str, int]]] = []   # (parq_idx, (seq, chg))
pi = 0   # parquet pointer
ki = 0   # pkl pointer
LOOKAHEAD = 3

while pi < len(parq) and ki < len(pkl):
    if parq[pi] == pkl[ki]:
        pi += 1
        ki += 1
        continue

    # 不一致：向前看，判断谁多了一行
    # 情况 A：parquet[pi] 是额外的 → parquet[pi+1] 应该等于 pkl[ki]
    is_parq_extra = (
        pi + 1 < len(parq) and parq[pi + 1] == pkl[ki]
    )
    # 情况 B：parquet[pi] 其实对应 pkl[ki+1] → pkl[ki] 是额外的（理论上不应发生）
    is_pkl_extra  = (
        ki + 1 < len(pkl) and parq[pi] == pkl[ki + 1]
    )

    if is_parq_extra:
        print(f"  [EXTRA-PARQ] pi={pi}: parquet 多行 {parq[pi]}")
        print(f"               pkl[ki={ki}]={pkl[ki]}  parq[pi+1]={parq[pi+1]}")
        extra_parq_rows.append((pi, parq[pi]))
        pi += 1   # 跳过这个额外的 parq 行，ki 不动
    elif is_pkl_extra:
        print(f"  [EXTRA-PKL] ki={ki}: pkl 多行 {pkl[ki]}  (意外情况)")
        ki += 1
    else:
        # 连续多行不一致或乱序 → 尝试 lookahead 对齐
        realigned = False
        for offset in range(2, LOOKAHEAD + 1):
            if pi + offset < len(parq) and parq[pi + offset] == pkl[ki]:
                print(f"  [EXTRA-PARQ*{offset}] pi={pi}~{pi+offset-1}: parquet 连续 {offset} 个额外行")
                for k in range(offset):
                    print(f"    parq[{pi+k}] = {parq[pi+k]}")
                    extra_parq_rows.append((pi+k, parq[pi+k]))
                pi += offset
                realigned = True
                break
        if not realigned:
            print(f"  [UNSYNC] pi={pi}, ki={ki}: 无法自动对齐！")
            print(f"    parq[pi]  = {parq[pi]}")
            print(f"    pkl[ki]   = {pkl[ki]}")
            print(f"    parq[pi+1..{pi+3}] = {parq[pi+1:pi+4]}")
            print(f"    pkl[ki+1..{ki+3}]  = {pkl[ki+1:ki+4]}")
            pi += 1
            ki += 1

# 末尾溢出
while pi < len(parq):
    extra_parq_rows.append((pi, parq[pi]))
    print(f"  [EXTRA-TAIL] pi={pi}: {parq[pi]}")
    pi += 1

# ── 结论 ─────────────────────────────────────────────────────────────────────
print(f"\n=== 结论 ===")
print(f"  parquet 共有 {len(extra_parq_rows)} 个额外行（pos.pkl 跳过）")
for pidx, (seq, chg) in extra_parq_rows:
    print(f"    parquet filtered 行号 {pidx}: ({seq}, z={chg})")

diff_expected = len(parq) - len(pkl)
print(f"  期望差: {diff_expected},  实际找到: {len(extra_parq_rows)}")

if len(extra_parq_rows) == diff_expected:
    print(f"\n  [方案A可行] 只需在 import 时维护一个 SKIP 集合:")
    print(f"  SKIP_ROWS = {{")
    for pidx, (seq, chg) in extra_parq_rows:
        print(f"    # parquet 过滤后行号 {pidx}")
    print(f"  }}")
    print(f"  导入时用 enumerate 计数，遇到这些行 source_row_counter 不递增即可。")
    print(f"  或更健壮：按 (seq,charge) 与 pkl 同步推进来写 source_row。")
else:
    print(f"\n  [需人工核查] 找到行数与预期不符，可能存在乱序或其他问题。")
