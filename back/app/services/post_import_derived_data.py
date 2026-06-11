"""Post-import hook for dataset derived-data generation."""

from __future__ import annotations

from app.core.db import session_scope
from app.services.derived_data_backfill import (
    DerivedDataBackfillResult,
    backfill_dataset_derived_data,
)


def build_post_import_derived_data(dataset_id: int) -> DerivedDataBackfillResult:
    """Generate all applicable derived data after the dataset transaction commits."""
    with session_scope() as session:
        return backfill_dataset_derived_data(session, dataset_id=dataset_id)
