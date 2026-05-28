#!/usr/bin/env python3
"""Form B end-to-end acceptance: path import → PFMB adapt → DB.

Same worker path as the frontend (POST /imports → background job).

Requires PostgreSQL, pfmb_bridge.exe, test/xzx_PXD045330/

Run:
  cd viewer-TD/test
  ..\\back\\.venv\\Scripts\\python.exe 形态B端到端验收.py
"""

from __future__ import annotations

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


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def main() -> None:
    if str(BACK_DIR) not in sys.path:
        sys.path.insert(0, str(BACK_DIR))

    if not PFMB_EXE.is_file():
        _fail(f"missing pfmb_bridge.exe: {PFMB_EXE}")
    if not DATASET.is_dir():
        _fail(f"missing dataset: {DATASET}")

    from sqlalchemy import text

    from app.core.config import settings
    from app.core.db import engine
    from app.services import import_jobs

    slug = f"formb-e2e-{uuid.uuid4().hex[:8]}"
    name = "Form B E2E xzx_PXD045330"
    source_path = str(DATASET.resolve())

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM datasets WHERE source_root LIKE :pattern"),
            {"pattern": "%\\adapted\\%"},
        )
        conn.execute(text("DELETE FROM datasets WHERE slug LIKE 'formb-e2e-%'"))

    job = import_jobs.create_job(
        slug=slug,
        name=name,
        description="Form B PFMB adapt e2e acceptance",
        source_path=source_path,
    )
    print(f"Running import job {job.job_id} slug={slug} …")
    import_jobs.run_path_import_job(
        job_id=job.job_id,
        source_path=source_path,
        slug=slug,
        name=name,
        description="Form B PFMB adapt e2e acceptance",
    )

    final = import_jobs.get_job(job.job_id)
    if final is None:
        _fail("job record missing after worker run")
    if final.status != "success":
        _fail(f"import failed: {final.error or final.stage_detail}")

    _ok(f"import job success ({final.stage_detail})")

    with engine.connect() as conn:
        ds = conn.execute(
            text(
                "SELECT dataset_id, analysis_mode, source_root "
                "FROM datasets WHERE slug = :slug"
            ),
            {"slug": slug},
        ).mappings().one()
        dataset_id = int(ds["dataset_id"])
        if str(ds["analysis_mode"]) != "TOP_DOWN":
            _fail(f"unexpected analysis_mode: {ds['analysis_mode']}")
        if "adapted" not in str(ds["source_root"]):
            _fail(f"expected adapted staging source_root, got {ds['source_root']}")
        _ok(f"dataset_id={dataset_id} source_root under adapted/")

        match_count = conn.execute(
            text("SELECT count(*) FROM identification_matches WHERE dataset_id = :id"),
            {"id": dataset_id},
        ).scalar()
        if int(match_count or 0) != 44:
            _fail(f"expected 44 identification_matches, got {match_count}")
        _ok(f"identification_matches={match_count}")

        prsm0 = conn.execute(
            text(
                """
                SELECT detail_path FROM identification_matches
                WHERE dataset_id = :id
                  AND jsonb_extract_path_text(extra_metadata, 'source_prsm_id') = '0'
                LIMIT 1
                """
            ),
            {"id": dataset_id},
        ).scalar()
        if not prsm0 or not Path(str(prsm0)).is_file():
            _fail(f"missing detail_path for prsm_id=0: {prsm0}")
        _ok(f"prsm0 detail on disk: {prsm0}")

        source_root = Path(str(ds["source_root"]))

    if not settings.pfmb_keep_binary_after_adapt:
        pfmb = source_root / "work" / "engine_out" / "results.pfmb"
        if pfmb.is_file():
            _fail(f"results.pfmb should be removed after adapt (JSON-only); still at {pfmb}")
        _ok("results.pfmb removed from this job staging (JSON-only delivery)")

    print(f"\nPASS: Form B e2e import (slug={slug})")


if __name__ == "__main__":
    main()
