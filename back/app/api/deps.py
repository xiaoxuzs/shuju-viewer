"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import Cutoff, Dataset


def get_db() -> Session:  # type: ignore[return-value]
    yield from get_session()


def get_dataset(slug: str, session: Session = Depends(get_db)) -> Dataset:
    dataset = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset not found: {slug}")
    return dataset


def get_cutoff(
    slug: str,
    cutoff: str,
    session: Session = Depends(get_db),
) -> Cutoff:
    dataset = get_dataset(slug, session)
    row = (
        session.execute(
            select(Cutoff).where(Cutoff.dataset_id == dataset.id, Cutoff.kind == cutoff)
        ).scalar_one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"cutoff not found: {cutoff}")
    return row
