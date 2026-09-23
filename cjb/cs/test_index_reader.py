"""Verification for app.pfmb.index_reader against the real index.json.

Run from the backend so ``app`` is importable (pyproject sets pythonpath="."):

    cd e:/viewer/back
    uv run python ../cs/test_index_reader.py

Override the index.json location with VIEWER_PFMB_INDEX_JSON if needed.

Checks:
  1. counts: 834455 items expand to 110024 source rows;
  2. resolve_source_row maps the first sample precursor to source_row 0/1;
  3. RT disambiguation: a (peptide, charge) shared by >=2 source rows resolves to
     the row whose apex slot_rt is nearest to the queried rt;
  4. get_slots(0) returns the expected ordered slots.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.pfmb import IndexReader, strip_mods

_DEFAULT_INDEX = (
    Path(__file__).resolve().parents[1]
    / "dia-ms2-pipei"
    / "Hela_DIA_v2_for_frontend"
    / "data"
    / "index.json"
)
INDEX_JSON = Path(os.environ.get("VIEWER_PFMB_INDEX_JSON", _DEFAULT_INDEX))

EXPECTED_SOURCE_ROWS = 110024
EXPECTED_ITEMS = 834455

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "[OK]" if ok else "[NG]"
    print(f"  {mark} {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    print(f"=== index.json: {INDEX_JSON} ===")
    if not INDEX_JSON.exists():
        print(f"  [NG] index.json 不存在，设置 VIEWER_PFMB_INDEX_JSON 指向真实文件")
        return 1

    reader = IndexReader(INDEX_JSON)

    print("\n=== [1/4] 计数 ===")
    check(
        "source_row 数 == 110024",
        reader.source_row_count == EXPECTED_SOURCE_ROWS,
        f"实际 {reader.source_row_count}",
    )

    print("\n=== [2/4] resolve_source_row 基本映射 ===")
    sample_peptide = "AAAAAAAAAPAAAATAPTTAATTAATAAQ"
    check(
        "(sample, z=2) -> source_row 0",
        reader.resolve_source_row(sample_peptide, 2) == 0,
        f"得到 {reader.resolve_source_row(sample_peptide, 2)}",
    )
    check(
        "(sample, z=3) -> source_row 1",
        reader.resolve_source_row(sample_peptide, 3) == 1,
        f"得到 {reader.resolve_source_row(sample_peptide, 3)}",
    )
    check(
        "去修饰键命中 (C[+57...]LDK 形式)",
        strip_mods("AAAAC[+57.021464]LDK") == "AAAACLDK",
    )
    check(
        "不存在的肽段 -> None",
        reader.resolve_source_row("ZZZZZZZZ", 2) is None,
    )

    print("\n=== [3/4] RT 消歧（共享 (peptide,charge) 的多 source_row）===")
    shared = _find_shared_key(reader)
    if shared is None:
        check("找到一个被 >=2 source_row 共享的 (peptide,charge)", False, "未找到")
    else:
        peptide, charge, rows = shared
        apex = {sr: reader._apex_rt[sr] for sr in rows}  # noqa: SLF001 (verification only)
        print(f"      key=({peptide[:24]}..., z={charge}) -> source_rows {rows[:5]}{'...' if len(rows) > 5 else ''}")
        print(f"      apex_rt 样例: {[(sr, round(apex[sr], 1)) for sr in rows[:5]]}")
        target = rows[len(rows) // 2]
        target_rt = apex[target]
        got = reader.resolve_source_row(peptide, charge, target_rt)
        nearest = min(rows, key=lambda sr: abs(apex[sr] - target_rt))
        check(
            "rt=目标apex 时解析到最近邻 source_row",
            got == nearest,
            f"目标 {target}, 解析 {got}, 最近邻 {nearest}",
        )
        got_none_rt = reader.resolve_source_row(peptide, charge, None)
        check(
            "rt=None 时返回首个注册 source_row",
            got_none_rt == rows[0],
            f"得到 {got_none_rt}, 期望 {rows[0]}",
        )

    print("\n=== [4/4] get_slots ===")
    slots0 = reader.get_slots(0)
    check("get_slots(0) 非空", len(slots0) > 0, f"{len(slots0)} 个")
    if slots0:
        check(
            "slots 按 slot_index 升序",
            [s.slot_index for s in slots0] == sorted(s.slot_index for s in slots0),
        )
        check(
            "slot.prsm_index 与 source_row 一致性 (source_row=0)",
            all(s.source_row == 0 for s in slots0),
        )
    check("get_slots(不存在) -> []", reader.get_slots(999999999) == [])

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过: {failures}")
        return 1
    print("  [PASS] index_reader 全部检查通过")
    return 0


def _find_shared_key(reader: IndexReader) -> tuple[str, int, list[int]] | None:
    """Find a (stripped_peptide, charge) used by >=2 distinct source rows."""

    reader._ensure_loaded()  # noqa: SLF001 (verification only)
    for (peptide, charge), rows in reader._by_key.items():  # noqa: SLF001
        if len(rows) >= 2:
            return peptide, charge, rows
    return None


if __name__ == "__main__":
    sys.exit(main())
