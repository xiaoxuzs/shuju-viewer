"""Shared FastAPI dependencies.

Only ``get_db`` is used by the v1 routes; the ORM-based ``get_dataset`` /
``get_cutoff`` helpers were removed together with the legacy ORM models since
the API now reads from the universal 7-table schema directly via ``text()``.
Slug / cutoff validation lives in :mod:`app.api.v1.universal_compat`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db import get_session


def get_db() -> Session:  # type: ignore[return-value]
    yield from get_session()
