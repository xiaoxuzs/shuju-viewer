"""Stable, client-safe errors for managed import uploads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UploadError(Exception):
    code: str
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message
