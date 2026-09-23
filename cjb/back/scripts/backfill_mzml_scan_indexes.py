from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import session_scope
from app.services.mzml_scan_index import (
    generate_scan_index_from_mzml,
    scan_index_paths,
    write_scan_index,
)
from app.services.mzml_scan_reader import resolve_run_mzml_path


def _dataset_row(session: Any, *, slug: str | None, dataset_id: int | None) -> dict[str, Any]:
    if slug is not None:
        row = session.execute(
            text("SELECT dataset_id, slug FROM datasets WHERE slug = :slug"),
            {"slug": slug},
        ).mappings().one_or_none()
    else:
        row = session.execute(
            text("SELECT dataset_id, slug FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).mappings().one_or_none()
    if row is None:
        raise SystemExit("dataset not found")
    return dict(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate lightweight mzML run scan indexes.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--slug", help="Dataset slug")
    target.add_argument("--dataset-id", type=int, help="datasets.dataset_id")
    parser.add_argument("--run-id", type=int, help="Only generate one run")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    with session_scope() as session:
        dataset = _dataset_row(session, slug=args.slug, dataset_id=args.dataset_id)
        params: dict[str, Any] = {"dataset_id": int(dataset["dataset_id"])}
        run_filter = ""
        if args.run_id is not None:
            run_filter = "AND run_id = :run_id"
            params["run_id"] = args.run_id
        rows = session.execute(
            text(
                f"""
                SELECT run_id
                FROM runs
                WHERE dataset_id = :dataset_id
                  AND (
                    jsonb_extract_path_text(run_metadata, 'raw_format') = 'mzml'
                    OR jsonb_extract_path_text(run_metadata, 'mzml_file_path') IS NOT NULL
                  )
                  {run_filter}
                ORDER BY run_id
                """
            ),
            params,
        ).mappings().all()
        if args.run_id is not None and not rows:
            raise SystemExit("mzML run not found")

        for row in rows:
            run_id = int(row["run_id"])
            source_path, _path_committed = resolve_run_mzml_path(
                session,
                int(dataset["dataset_id"]),
                run_id,
            )
            started = time.perf_counter()
            index = generate_scan_index_from_mzml(source_path)
            metadata = write_scan_index(
                dataset_id=int(dataset["dataset_id"]),
                run_id=run_id,
                source_path=source_path,
                index=index,
            )
            elapsed = time.perf_counter() - started
            npz_path, metadata_path = scan_index_paths(int(dataset["dataset_id"]), run_id)
            results.append(
                {
                    "run_id": run_id,
                    "source_path": metadata["source_path"],
                    "source_size": metadata["source_size"],
                    "scan_count": metadata["scan_count"],
                    "ms1_count": metadata["ms1_count"],
                    "ms2_count": metadata["ms2_count"],
                    "elapsed_seconds": round(elapsed, 6),
                    "npz_path": str(npz_path),
                    "npz_size": npz_path.stat().st_size,
                    "json_path": str(metadata_path),
                }
            )

    print(
        json.dumps(
            {
                "dataset_id": int(dataset["dataset_id"]),
                "slug": dataset["slug"],
                "runs": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
