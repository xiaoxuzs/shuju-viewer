"""Chromatogram service placeholders for PR-3."""

from __future__ import annotations

from fastapi import HTTPException, status


def unsupported() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")

