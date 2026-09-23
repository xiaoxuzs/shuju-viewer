"""Verification for app.pfmb.reader against the real results.pfmb.

Run from the backend so ``app`` is importable (pyproject sets pythonpath="."):

    cd e:/viewer/back
    $env:PYTHONPATH="."; uv run python ../cs/test_pfmb_reader.py

Overrides:
  VIEWER_PFMB_RESULTS  -> results.pfmb location
  VIEWER_PFM_DIR       -> directory containing pfm.py (if not auto-found)

Checks:
  1. bundle opens, record count == 834455;
  2. read(0) returns peptide matching the index.json sample, with matched ions;
  3. ion_type values are within {b, y, c, z_dot};
  4. prsm_index == record_index (O(1) fast path holds) for sampled indices;
  5. mass-error ppm is small and intensities positive (sanity).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.pfmb import PfmbAnnotationReader

_DEFAULT_PFMB = (
    Path(__file__).resolve().parents[1]
    / "dia-ms2-pipei"
    / "Hela_DIA_v2_for_frontend"
    / "data"
    / "results.pfmb"
)
PFMB_PATH = Path(os.environ.get("VIEWER_PFMB_RESULTS", _DEFAULT_PFMB))

EXPECTED_COUNT = 834455
SAMPLE_PEPTIDE = "AAAAAAAAAPAAAATAPTTAATTAATAAQ"
ALLOWED_SERIES = {"b", "y", "c", "z_dot"}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "[OK]" if ok else "[NG]"
    print(f"  {mark} {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    print(f"=== results.pfmb: {PFMB_PATH} ===")
    if not PFMB_PATH.exists():
        print("  [NG] results.pfmb 不存在，设置 VIEWER_PFMB_RESULTS 指向真实文件")
        return 1

    with PfmbAnnotationReader(PFMB_PATH) as reader:
        print("\n=== [1/5] 计数 ===")
        check("record count == 834455", len(reader) == EXPECTED_COUNT, f"实际 {len(reader)}")

        print("\n=== [2/5] read(0) ===")
        ann0 = reader.read(0)
        check("prsm_index == 0", ann0.prsm_index == 0, f"得到 {ann0.prsm_index}")
        check("peptide == 样例肽段", ann0.peptide == SAMPLE_PEPTIDE, f"得到 {ann0.peptide!r}")
        check("matched_ions 非空", len(ann0.matched_ions) > 0, f"{len(ann0.matched_ions)} 个")
        print(f"      scan={ann0.scan}  matched_peak_count={ann0.matched_peak_count}")
        for ion in ann0.matched_ions[:5]:
            print(
                f"      {ion.ion_type}{ion.fragment_ordinal} z={ion.charge} "
                f"ppm={ion.mass_error_ppm:.3f} int={ion.intensity:.0f} peak={ion.peak_id}"
            )

        print("\n=== [3/5] ion_type 取值 ===")
        series_seen = {ion.ion_type for ion in ann0.matched_ions}
        check("ion_type 都在 {b,y,c,z_dot}", series_seen <= ALLOWED_SERIES, f"出现 {series_seen}")

        print("\n=== [4/5] prsm_index == record_index (O(1) 路径) ===")
        for idx in [0, 1, 7, 8, 100, 5000, EXPECTED_COUNT - 1]:
            ann = reader.read(idx)
            check(f"read({idx}).prsm_index == {idx}", ann.prsm_index == idx, f"得到 {ann.prsm_index}")

        print("\n=== [5/5] 数值合理性 ===")
        bad_ppm = [i for i in ann0.matched_ions if abs(i.mass_error_ppm) > 50]
        check("所有 |ppm| < 50", not bad_ppm, f"{len(bad_ppm)} 个超界")
        check("所有 intensity >= 0", all(i.intensity >= 0 for i in ann0.matched_ions))

    print("\n=== 总结 ===")
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过: {failures}")
        return 1
    print("  [PASS] pfmb reader 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
