from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bu.services.protein_sequence_backfill import backfill_protein_sequences_from_fasta
from app.core.db import engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Bottom-Up protein base_sequence from a local FASTA.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--slug", help="Dataset slug, for example bu_pr1_dia")
    target.add_argument("--dataset-id", type=int, help="datasets.dataset_id")
    args = parser.parse_args()

    with engine.begin() as conn:
        if args.slug:
            row = conn.execute(
                text(
                    """
                    SELECT dataset_id, slug, source_root, analysis_mode
                    FROM datasets
                    WHERE slug = :slug
                    """
                ),
                {"slug": args.slug},
            ).mappings().one_or_none()
        else:
            row = conn.execute(
                text(
                    """
                    SELECT dataset_id, slug, source_root, analysis_mode
                    FROM datasets
                    WHERE dataset_id = :dataset_id
                    """
                ),
                {"dataset_id": args.dataset_id},
            ).mappings().one_or_none()
        if row is None:
            raise SystemExit("dataset not found")
        if str(row.get("analysis_mode") or "").upper() != "BOTTOM_UP":
            raise SystemExit("dataset is not BOTTOM_UP")

        stats = backfill_protein_sequences_from_fasta(
            conn,
            dataset_id=int(row["dataset_id"]),
            source_root=Path(str(row.get("source_root") or "")),
        )

    print(
        json.dumps(
            {
                "dataset_id": int(row["dataset_id"]),
                "slug": row["slug"],
                "source_root": row["source_root"],
                "sequence_backfill": stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
