#!/usr/bin/env python3
"""TopPIC admission (file discrimination) acceptance for viewer-TD.

Validates :mod:`app.toppic_admission` against:
  - synthetic tmp layouts (via pytest in back/tests/test_toppic_admission_*.py)
  - real Form B sample: test/xzx_PXD045330/

Run:
  cd viewer-TD/test
  python 文件判别验收.py

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
BACK_DIR = TEST_DIR.parent / "back"
DATASET_ROOT = TEST_DIR / "xzx_PXD045330"
RUN_PREFIX = "20191118_rvg262_LT_110516-13_1000-1100_Techrep01"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def _run_pytest_admission() -> None:
    print("\n== pytest: toppic_admission unit tests ==")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_toppic_admission_signals.py",
        "tests/test_toppic_admission_pairing.py",
        "tests/test_toppic_admission_classify.py",
        "tests/test_dataset_ingest_root.py",
        "-q",
    ]
    proc = subprocess.run(cmd, cwd=BACK_DIR, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    if proc.returncode != 0:
        _fail(f"pytest admission suite exited {proc.returncode}")
    _ok("pytest admission suite passed")


def _import_admission():
    if str(BACK_DIR) not in sys.path:
        sys.path.insert(0, str(BACK_DIR))
    from app.toppic_admission import AdmissionRoute, classify_admission, classify_user_path

    return AdmissionRoute, classify_admission, classify_user_path


def _check_real_form_b() -> None:
    print("\n== real dataset: xzx_PXD045330 (Form B) ==")
    if not DATASET_ROOT.is_dir():
        _fail(f"missing dataset directory: {DATASET_ROOT}")

    AdmissionRoute, classify_admission, classify_user_path = _import_admission()

    decision = classify_user_path(DATASET_ROOT)
    if decision.route != AdmissionRoute.NEED_PFMB:
        _fail(
            f"expected route=need_pfmb, got {decision.route.value!r}; "
            f"reject={decision.reject_code}: {decision.reject_reason}"
        )
    if len(decision.run_triples) != 1:
        _fail(f"expected 1 run triple, got {len(decision.run_triples)}")

    triple = decision.run_triples[0]
    expected_key = RUN_PREFIX.lower()
    if triple.run_key != expected_key:
        _fail(f"run_key mismatch: {triple.run_key!r} != {expected_key!r}")

    for label, path, expected_name in (
        ("prsm_xml", triple.prsm_xml, f"{RUN_PREFIX}_ms2_toppic_prsm.xml"),
        ("ms2_msalign", triple.ms2_msalign, f"{RUN_PREFIX}_ms2.msalign"),
        ("mzml", triple.mzml, f"{RUN_PREFIX}.mzML"),
    ):
        if not path.is_file():
            _fail(f"{label} path missing on disk: {path}")
        if path.name != expected_name:
            _fail(f"{label} name mismatch: {path.name!r} != {expected_name!r}")

    _ok(
        f"Form B classified; triple xml/msalign/mzml paired for run '{triple.run_key}'"
    )


def _check_reject_english_only_mzml() -> None:
    print("\n== synthetic reject: only mzML (English reason) ==")
    AdmissionRoute, classify_admission, _ = _import_admission()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "orphan.mzML").write_text("<mzML />", encoding="utf-8")
        decision = classify_admission(root)
        if decision.route != AdmissionRoute.UNSUPPORTED:
            _fail(f"expected unsupported for only mzML, got {decision.route.value}")
        reason = decision.reject_reason or ""
        if not reason.isascii():
            _fail(f"reject_reason should be English ASCII, got: {reason!r}")
        if "mzML" not in reason and "mzml" not in reason.lower():
            _fail(f"reject_reason missing mzML context: {reason!r}")
        _ok(f"only_mzml reject: {reason[:80]}...")


def _check_reject_english_missing_mzml_on_real_layout() -> None:
    print("\n== synthetic reject: pipeline without mzML (English reason) ==")
    AdmissionRoute, classify_admission, _ = _import_admission()
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "no_mzml_copy"
        shutil.copytree(DATASET_ROOT, staging, ignore=shutil.ignore_patterns("*.mzML", "*.mzml"))
        decision = classify_admission(staging)
        if decision.route != AdmissionRoute.UNSUPPORTED:
            _fail(f"expected unsupported without mzML, got {decision.route.value}")
        if decision.reject_code != "missing_mzml":
            _fail(f"expected reject_code=missing_mzml, got {decision.reject_code!r}")
        reason = decision.reject_reason or ""
        if "No mzML spectra files were found" not in reason:
            _fail(f"unexpected reject_reason: {reason!r}")
        _ok(f"missing_mzml reject: {reason[:80]}...")


def main() -> None:
    print("TopPIC admission acceptance (viewer-TD/test/文件判别验收.py)")
    _run_pytest_admission()
    _check_real_form_b()
    _check_reject_english_only_mzml()
    _check_reject_english_missing_mzml_on_real_layout()
    print("\nPASS: all admission acceptance checks passed.")


if __name__ == "__main__":
    main()
