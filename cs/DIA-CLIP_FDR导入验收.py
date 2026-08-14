"""只读验收 DIA-CLIP FDR parquet + mzML 导入契约。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "back"))

from app.ingest.bu.diaclip_fdr_result_reader import prepare_diaclip_fdr_source  # noqa: E402
from app.ingest.bu.diaclip_source import inspect_diaclip_source  # noqa: E402
from app.services.import_planner import plan_zip_ingest  # noqa: E402


def _expected_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是整数。") from exc


def main() -> None:
    root_raw = os.environ.get("VIEWER_DIACLIP_FDR_DATASET_ROOT")
    if not root_raw:
        raise SystemExit("请先设置 VIEWER_DIACLIP_FDR_DATASET_ROOT 指向待验收的上传目录。")
    root = Path(root_raw).expanduser().resolve()

    inspection = inspect_diaclip_source(root)
    if inspection.kind != "fdr_parquet":
        raise SystemExit(f"期望 fdr_parquet，实际为 {inspection.kind}。")

    plan = plan_zip_ingest(root)
    prepared = prepare_diaclip_fdr_source(root)
    stats = prepared.stats

    failures: list[str] = []
    expected_total = _expected_int("VIEWER_DIACLIP_FDR_EXPECTED_TOTAL_ROWS")
    expected_accepted = _expected_int("VIEWER_DIACLIP_FDR_EXPECTED_ACCEPTED_TARGETS")
    expected_decoy = _expected_int("VIEWER_DIACLIP_FDR_EXPECTED_DECOY_ROWS")
    if expected_total is not None and stats.parquet_total_rows != expected_total:
        failures.append(f"total_rows expected={expected_total}, actual={stats.parquet_total_rows}")
    if expected_accepted is not None and stats.accepted_targets != expected_accepted:
        failures.append(f"accepted_targets expected={expected_accepted}, actual={stats.accepted_targets}")
    if expected_decoy is not None and stats.decoy_rows != expected_decoy:
        failures.append(f"decoy_rows expected={expected_decoy}, actual={stats.decoy_rows}")

    print(f"root={root}")
    print(f"kind={inspection.kind}")
    print(f"result_path={inspection.result_path}")
    print(f"run_names={sorted(inspection.report_info.run_names)}")
    print(f"plan_shape={plan.shape.value}")
    print(f"spectra_source={plan.spectra_source}")
    print(f"mzml_files={[str(path) for path in plan.mzml_files]}")
    print(f"total_rows={stats.parquet_total_rows}")
    print(f"accepted_targets={stats.accepted_targets}")
    print(f"decoy_rows={stats.decoy_rows}")
    print(f"failed_rows={stats.failed_rows}")
    print(f"import_mode={prepared.source.import_mode}")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("PASS")


if __name__ == "__main__":
    main()
