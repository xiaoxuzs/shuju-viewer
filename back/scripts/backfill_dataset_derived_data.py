from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import session_scope
from app.services.derived_data_backfill import (
    DerivedDataBackfillArgumentError,
    backfill_dataset_derived_data,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and validate dataset derived data."
    )
    parser.add_argument("--dataset-id", type=int, help="datasets.dataset_id")
    parser.add_argument("--slug", help="Dataset slug")
    parser.add_argument("--run-id", type=int, help="Only process one run")
    parser.add_argument(
        "--only",
        choices=("scan-index", "chromatogram"),
        help="Only process one derived data type",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate ready data")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report status; do not write files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with session_scope() as session:
            result = backfill_dataset_derived_data(
                session,
                dataset_id=args.dataset_id,
                slug=args.slug,
                run_id=args.run_id,
                only=args.only,
                force=args.force,
                check_only=args.check_only,
            )
    except DerivedDataBackfillArgumentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "dataset_id": result.dataset_id,
                "dataset_slug": result.dataset_slug,
                "runs": [asdict(run) for run in result.runs],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
