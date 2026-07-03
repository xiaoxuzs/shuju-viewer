"""Print read-only dataset/run metadata for Viewer RAW or mzML imports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def _repo_back_path() -> Path:
    return Path(__file__).resolve().parents[1] / "back"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--needle", default="raw-thermo", help="Case-insensitive path or metadata search text.")
    parser.add_argument("--stem", default="ch_23Aug2018_HeLa_Std_1", help="Case-insensitive run file stem.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(_repo_back_path()))
    from app.core.config import settings

    engine = create_engine(settings.database_url, future=True)
    with engine.connect() as conn:
        conn.execute(text("BEGIN READ ONLY"))
        try:
            rows = conn.execute(
                text(
                    """
                    SELECT d.dataset_id,
                           d.slug,
                           d.dataset_name,
                           d.description,
                           d.analysis_mode,
                           d.status,
                           d.source_software,
                           d.source_root,
                           d.capabilities,
                           d.extra_metadata,
                           r.run_id,
                           r.file_name,
                           r.file_path,
                           r.run_metadata
                    FROM datasets d
                    JOIN runs r ON r.dataset_id = d.dataset_id
                    WHERE d.source_root ILIKE :needle
                       OR r.file_path ILIKE :needle
                       OR r.file_name ILIKE :stem
                       OR CAST(r.run_metadata AS text) ILIKE :needle
                    ORDER BY d.dataset_id, r.run_id
                    """
                ),
                {
                    "needle": f"%{args.needle}%",
                    "stem": f"%{args.stem}%",
                },
            ).mappings().all()
        finally:
            conn.execute(text("ROLLBACK"))

    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
