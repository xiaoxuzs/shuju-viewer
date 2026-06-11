from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bu.services.chromatogram_summary import (
    generate_summary_from_mzml,
    resolve_run_source_path,
    write_summary,
)
from app.core.db import engine


def _dataset_row(connection: Any, *, slug: str | None, dataset_id: int | None) -> dict[str, Any]:
    if slug is not None:
        row = connection.execute(
            text(
                """
                SELECT dataset_id, slug, analysis_mode
                FROM datasets
                WHERE slug = :slug
                """
            ),
            {"slug": slug},
        ).mappings().one_or_none()
    else:
        row = connection.execute(
            text(
                """
                SELECT dataset_id, slug, analysis_mode
                FROM datasets
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        ).mappings().one_or_none()
    if row is None:
        raise SystemExit("dataset not found")
    if str(row.get("analysis_mode") or "").upper() != "BOTTOM_UP":
        raise SystemExit("dataset is not BOTTOM_UP")
    return dict(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Bottom-Up mzML TIC/BPC summaries.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--slug", help="Dataset slug, for example bu_pr1_dia")
    target.add_argument("--dataset-id", type=int, help="datasets.dataset_id")
    parser.add_argument("--run-id", type=int, help="Only generate one run")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    with engine.connect() as connection:
        dataset = _dataset_row(connection, slug=args.slug, dataset_id=args.dataset_id)
        params: dict[str, Any] = {"dataset_id": int(dataset["dataset_id"])}
        run_filter = ""
        if args.run_id is not None:
            run_filter = "AND run_id = :run_id"
            params["run_id"] = args.run_id
        rows = connection.execute(
            text(
                f"""
                SELECT run_id, file_path, run_metadata
                FROM runs
                WHERE dataset_id = :dataset_id
                  AND jsonb_extract_path_text(run_metadata, 'raw_format') = 'mzml'
                  {run_filter}
                ORDER BY run_id
                """
            ),
            params,
        ).mappings().all()
        if args.run_id is not None and not rows:
            raise SystemExit("mzML run not found")

        for row in rows:
            run = dict(row)
            run_id = int(run["run_id"])
            source_path = resolve_run_source_path(run)
            summary = generate_summary_from_mzml(source_path)
            metadata = write_summary(
                dataset_id=int(dataset["dataset_id"]),
                run_id=run_id,
                source_path=source_path,
                summary=summary,
            )
            results.append(
                {
                    "run_id": run_id,
                    "source_path": metadata["source_path"],
                    "points_count": metadata["points_count"],
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
