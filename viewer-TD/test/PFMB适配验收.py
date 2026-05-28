#!/usr/bin/env python3
"""End-to-end PFMB adapt acceptance (Form B → staging prsm*.json).

Requires:
  - viewer-TD/PFMB/pfmb_bridge.exe
  - test/xzx_PXD045330/
  - writable shuju/adapted/ (or VIEWER_DATA_ROOT)

Run:
  cd viewer-TD/test
  python PFMB适配验收.py
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
BACK_DIR = TEST_DIR.parent / "back"
DATASET = TEST_DIR / "xzx_PXD045330"
PFMB_EXE = TEST_DIR.parent / "PFMB" / "pfmb_bridge.exe"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if str(BACK_DIR) not in sys.path:
        sys.path.insert(0, str(BACK_DIR))

    from app.toppic_admission import AdmissionRoute, classify_user_path, run_pfmb_adapt

    if not PFMB_EXE.is_file():
        _fail(f"missing pfmb_bridge.exe: {PFMB_EXE}")
    if not DATASET.is_dir():
        _fail(f"missing dataset: {DATASET}")

    decision = classify_user_path(DATASET)
    if decision.route != AdmissionRoute.NEED_PFMB:
        _fail(f"expected need_pfmb, got {decision.route.value}: {decision.reject_reason}")

    job_id = f"accept-{uuid.uuid4().hex[:8]}"
    print(f"Running PFMB adapt job_id={job_id} …")
    result = run_pfmb_adapt(decision, job_id=job_id, pfmb_exe=PFMB_EXE)
    print(f"OK staging={result.staging_root} prsm_json={result.prsm_json_count}")

    prsm0 = result.staging_root / "data" / "prsms" / "prsm0.json"
    if not prsm0.is_file():
        _fail(f"missing assembled file: {prsm0}")

    # Optional cleanup: keep staging for inspection; uncomment to remove
    # shutil.rmtree(result.staging_root, ignore_errors=True)
    print("PASS: PFMB adapt acceptance complete.")


if __name__ == "__main__":
    main()
