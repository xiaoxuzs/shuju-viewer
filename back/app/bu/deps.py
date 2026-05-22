"""Bottom-Up API dependencies and mode guards."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.universal_compat import require_dataset


def require_bu_dataset(session: Session, slug: str) -> dict[str, Any]:
    """Load a dataset and require ``analysis_mode = BOTTOM_UP``."""
    dataset = require_dataset(session, slug)
    if str(dataset.get("analysis_mode") or "").upper() != "BOTTOM_UP":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_bottom_up")
    return dataset


def require_bu_match(session: Session, dataset_id: int, match_id: int) -> dict[str, Any]:
    """Load a BU peptide match by DB primary key."""
    row = session.execute(
        text(
            """
            SELECT
                im.*, p.sequence, r.file_name AS run_name, r.file_path, r.run_metadata
            FROM identification_matches im
            JOIN peptides p
              ON p.dataset_id = im.dataset_id
             AND p.peptide_id = im.entity_id
            JOIN runs r
              ON r.dataset_id = im.dataset_id
             AND r.run_id = im.run_id
            WHERE im.dataset_id = :dataset_id
              AND im.match_id = :match_id
              AND im.entity_type = 'PEPTIDE'
            """
        ),
        {"dataset_id": dataset_id, "match_id": match_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="match_not_found")
    return dict(row)

