"""Structured RAW conversion errors."""

from __future__ import annotations

from app.raw_conversion.contracts import RawConversionResult


class RawConversionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        result: RawConversionResult | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.result = result
