"""Spectrum facade placeholders for PR-3."""

from __future__ import annotations

from fastapi import HTTPException, status


def spectrum_not_implemented() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="not_implemented")

