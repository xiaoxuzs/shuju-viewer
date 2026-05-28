#!/usr/bin/env python3
"""PFMB 模块验收（对齐 PFMB_BRIDGE_EXE.md）。

主程序：viewer-TD/PFMB/pfmb_bridge.exe

必验链路（交付约定）：
  ingest  → prsm.cache
  run     → engine_out/results.pfmb（二进制主结果）

可选联调（本脚本默认也跑，可用 --skip-egress 跳过）：
  egress  → JSON/CSV，供人工联调

Python 读二进制（pfmb_io.py，见 DEVELOPER_PFMB.md）：
  依赖同目录 pfm.py；缺失则 SKIP 并提示

运行：
  cd viewer-TD/test
  python pfmb_验收.py
  python pfmb_验收.py --skip-egress
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
VIEWER_TD_ROOT = TEST_DIR.parent
PFMB_DIR = VIEWER_TD_ROOT / "PFMB"
PFMB_EXE = PFMB_DIR / "pfmb_bridge.exe"
PFMB_IO = PFMB_DIR / "pfmb_io.py"
PFM_MODULE = PFMB_DIR / "pfm.py"
DATASET_ROOT = TEST_DIR / "xzx_PXD045330"
WORK_DIR = TEST_DIR / "pfmb_work"

RUN_PREFIX = "20191118_rvg262_LT_110516-13_1000-1100_Techrep01"
PRSM_XML = DATASET_ROOT / "toppic" / f"{RUN_PREFIX}_ms2_toppic_prsm.xml"
MS2_MSALIGN = DATASET_ROOT / "topfd" / f"{RUN_PREFIX}_ms2.msalign"
MZML = DATASET_ROOT / f"{RUN_PREFIX}.mzML"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)


def _safe_print(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    enc = getattr(stream, "encoding", None) or "utf-8"
    safe = text.rstrip().encode(enc, errors="replace").decode(enc, errors="replace")
    print(safe, file=stream)


def _parse_bridge_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    _fail(f"pfmb_bridge 未输出可解析的单行 JSON\n{stdout[-2000:]}")


def _run_bridge(args: list[str], *, step: str) -> dict:
    """调用 pfmb_bridge.exe；参数与 PFMB_BRIDGE_EXE.md 一致。"""
    if not PFMB_EXE.is_file():
        _fail(f"缺少主程序 {PFMB_EXE}")
    cmd = [str(PFMB_EXE), *args]
    print(f"\n== {step} (pfmb_bridge.exe) ==")
    print(" ".join(cmd))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(TEST_DIR),
    )
    merged = (proc.stdout or "") + (proc.stderr or "")
    if proc.stdout:
        _safe_print(proc.stdout)
    if proc.stderr:
        _safe_print(proc.stderr, err=True)
    if proc.returncode != 0:
        _fail(f"{step} 退出码 {proc.returncode}")
    payload = _parse_bridge_json(merged)
    if not payload.get("ok"):
        _fail(f"{step} 返回 ok=false: {payload}")
    return payload


def _assert_dataset_layout() -> None:
    missing = [p for p in (PRSM_XML, MS2_MSALIGN, MZML) if not p.is_file()]
    if missing:
        _fail("测试数据不完整，缺少:\n" + "\n".join(f"  - {p}" for p in missing))


def _assert_pfmb_binary(path: Path) -> None:
    """DEVELOPER_PFMB.md：魔数 PFMB。"""
    if not path.is_file():
        _fail(f"缺少二进制主结果 {path}")
    magic = path.read_bytes()[:4]
    if magic != b"PFMB":
        _fail(f"{path} 魔数应为 PFMB，实际 {magic!r}")


def _run_ingest_run(*, work: Path) -> tuple[int, Path]:
    """PFMB_BRIDGE_EXE.md §2.2 + §3。"""
    cache = work / "prsm.cache"
    manifest = work / "cache_build.manifest.json"
    engine_out = work / "engine_out"
    pfmb_path = engine_out / "results.pfmb"
    summary_path = engine_out / "summary.json"

    ingest_out = _run_bridge(
        [
            "ingest",
            "--source",
            "xml_msalign",
            "--prsm-xml",
            str(PRSM_XML),
            "--ms2-msalign",
            str(MS2_MSALIGN),
            "--cache",
            str(cache),
            "--manifest",
            str(manifest),
        ],
        step="ingest (§2.2 xml_msalign)",
    )
    record_count = int(ingest_out.get("records") or 0)
    if record_count <= 0:
        _fail(f"ingest records={record_count}")
    if not cache.is_file():
        _fail(f"未生成 {cache}")

    run_out = _run_bridge(
        [
            "run",
            "--cache",
            str(cache),
            "--output",
            str(engine_out),
            "--preset",
            "native_coverage",
            "--rebuild-frag-cache",
        ],
        step="run (§3 → results.pfmb)",
    )
    if run_out.get("pfmb"):
        candidate = Path(str(run_out["pfmb"]))
        if candidate.is_file():
            pfmb_path = candidate
    _assert_pfmb_binary(pfmb_path)

    if not summary_path.is_file():
        _fail(f"未生成 {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    processed = int(summary.get("counts", {}).get("processed_ok", 0))
    if processed != record_count:
        _fail(f"run processed_ok={processed} != ingest records={record_count}")

    print(f"\nOK core: ingest + run -> {pfmb_path} ({record_count} PRSM)")
    return record_count, pfmb_path


def _run_egress(*, work: Path, pfmb_path: Path, record_count: int) -> None:
    """PFMB_BRIDGE_EXE.md §4 — 可选联调。"""
    cache = work / "prsm.cache"
    egress_dir = work / "egress"
    egress_dir.mkdir(parents=True, exist_ok=True)

    _run_bridge(
        [
            "egress",
            "--cache",
            str(cache),
            "--pfmb",
            str(pfmb_path),
            "--prsm",
            "0",
            "--format",
            "json",
            "--out",
            str(egress_dir / "prsm0_peaks.json"),
        ],
        step="egress single (§4.1 联调)",
    )

    egress_all = _run_bridge(
        [
            "egress",
            "--cache",
            str(cache),
            "--pfmb",
            str(pfmb_path),
            "--all",
            "--format",
            "json",
            "--out-dir",
            str(egress_dir),
        ],
        step="egress all (§4.2 联调)",
    )

    peaks0 = json.loads((egress_dir / "prsm0_peaks.json").read_text(encoding="utf-8"))
    rows = peaks0.get("rows")
    if not isinstance(rows, list) or not rows:
        _fail("egress: prsm0_peaks.json 缺少非空 rows[]")
    if not any(r.get("matched") for r in rows):
        _fail("egress: prsm0_peaks.json 无 matched=true 行")

    index_doc = json.loads((egress_dir / "_index.json").read_text(encoding="utf-8"))
    items = index_doc.get("items")
    total_prsm = int(index_doc.get("total_prsm") or egress_all.get("total_prsm") or 0)
    if total_prsm != record_count or not isinstance(items, list) or len(items) != total_prsm:
        _fail("egress: _index.json 与 ingest 记录数不一致")
    if len(list(egress_dir.glob("prsm*_peaks.json"))) != total_prsm:
        _fail("egress: peaks 文件数与 total_prsm 不一致")

    ratio = egress_all.get("matched_peak_ratio")
    print(f"OK egress (optional): {total_prsm} files, matched_peak_ratio={ratio}")


def _run_pfmb_io(*, pfmb_path: Path) -> None:
    """DEVELOPER_PFMB.md + pfmb_io.py — Python 直读二进制。"""
    if not PFMB_IO.is_file():
        _warn(f"跳过 pfmb_io：缺少 {PFMB_IO}")
        return
    if not PFM_MODULE.is_file():
        _warn(
            "跳过 pfmb_io：缺少 PFMB/pfm.py（pfmb_io.py 依赖 pfm 模块）。"
            "请补齐交付包后再验 Python 联调路径。"
        )
        return

    spec = importlib.util.spec_from_file_location("pfmb_io", PFMB_IO)
    if spec is None or spec.loader is None:
        _fail("无法加载 pfmb_io.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PFMB_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        if str(PFMB_DIR) in sys.path:
            sys.path.remove(str(PFMB_DIR))

    reader_cls = getattr(module, "PfmbReader")
    with reader_cls(str(pfmb_path)) as reader:
        count = reader.record_count
        if count <= 0:
            _fail("pfmb_io: record_count <= 0")
        rec = reader.read_record(0)
        n_matches = len(rec.matches)
        print(
            f"OK pfmb_io: record_count={count}, "
            f"read_record(0) prsm_index={rec.prsm_index} matches={n_matches}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="PFMB module acceptance (viewer-TD/test)")
    parser.add_argument(
        "--skip-egress",
        action="store_true",
        help="只验 ingest+run（主链路）；跳过 egress 联调",
    )
    parser.add_argument(
        "--skip-pfmb-io",
        action="store_true",
        help="跳过 pfmb_io.py Python 读二进制",
    )
    args = parser.parse_args()

    _assert_dataset_layout()

    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)

    record_count, pfmb_path = _run_ingest_run(work=WORK_DIR)

    if not args.skip_egress:
        _run_egress(work=WORK_DIR, pfmb_path=pfmb_path, record_count=record_count)
    else:
        print("\nSKIP egress (optional 联调，见 --help)")

    if not args.skip_pfmb_io:
        _run_pfmb_io(pfmb_path=pfmb_path)
    else:
        print("\nSKIP pfmb_io")

    print(f"\nPFMB acceptance passed (work={WORK_DIR})")


if __name__ == "__main__":
    main()
