"""Shared accounting primitives for bounded source inspectors."""

from __future__ import annotations

import hashlib
import io
import time
from typing import BinaryIO, Literal

from .contracts import BudgetUsage, InspectionLimits


BudgetReason = Literal["bytes", "rows", "elements", "time"]


class InspectionBudgetExceeded(RuntimeError):
    def __init__(self, reason: BudgetReason) -> None:
        super().__init__(f"inspection {reason} budget exhausted")
        self.reason = reason


class BudgetTracker:
    def __init__(self, limits: InspectionLimits) -> None:
        self.limits = limits
        self.started = time.perf_counter()
        self.bytes_read = 0
        self.rows_read = 0
        self.elements_read = 0
        self._exhausted: list[BudgetReason] = []
        self._sample_digest = hashlib.sha256()

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.limits.max_bytes_read - self.bytes_read)

    @property
    def sample_sha256(self) -> str:
        return self._sample_digest.hexdigest()

    @property
    def exhausted(self) -> tuple[BudgetReason, ...]:
        return tuple(self._exhausted)

    def mark_exhausted(self, reason: BudgetReason) -> None:
        if reason not in self._exhausted:
            self._exhausted.append(reason)

    def check_time(self) -> None:
        if self.elapsed_seconds >= self.limits.max_seconds:
            self.mark_exhausted("time")
            raise InspectionBudgetExceeded("time")

    def record_bytes(self, value: bytes) -> None:
        self.check_time()
        if len(value) > self.remaining_bytes:
            self.mark_exhausted("bytes")
            raise InspectionBudgetExceeded("bytes")
        self.bytes_read += len(value)
        self._sample_digest.update(value)

    def take_row(self) -> None:
        self.check_time()
        if self.rows_read >= self.limits.max_rows:
            self.mark_exhausted("rows")
            raise InspectionBudgetExceeded("rows")
        self.rows_read += 1

    def take_element(self) -> None:
        self.check_time()
        if self.elements_read >= self.limits.max_elements:
            self.mark_exhausted("elements")
            raise InspectionBudgetExceeded("elements")
        self.elements_read += 1

    def usage(self) -> BudgetUsage:
        if self.elapsed_seconds >= self.limits.max_seconds:
            self.mark_exhausted("time")
        return BudgetUsage(
            limits=self.limits,
            bytes_read=self.bytes_read,
            rows_read=self.rows_read,
            elements_read=self.elements_read,
            elapsed_ms=self.elapsed_seconds * 1000,
            exhausted=list(self._exhausted),
        )


class BudgetedReader(io.RawIOBase):
    """Seekable binary wrapper that meters each physical read request."""

    def __init__(self, stream: BinaryIO, tracker: BudgetTracker, *, file_size: int) -> None:
        super().__init__()
        self._stream = stream
        self._tracker = tracker
        self._file_size = file_size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._stream.fileno()

    def tell(self) -> int:
        return self._stream.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._tracker.check_time()
        return self._stream.seek(offset, whence)

    def read(self, size: int = -1) -> bytes:
        self._tracker.check_time()
        current = self._stream.tell()
        if current >= self._file_size:
            return b""
        if size == 0:
            return b""
        remaining_budget = self._tracker.remaining_bytes
        if remaining_budget <= 0:
            self._tracker.mark_exhausted("bytes")
            raise InspectionBudgetExceeded("bytes")

        remaining_file = max(0, self._file_size - current)
        requested = remaining_file if size is None or size < 0 else max(0, size)
        allowed = min(requested, remaining_budget)
        data = self._stream.read(allowed)
        self._tracker.record_bytes(data)
        if requested > allowed and len(data) == allowed and self._stream.tell() < self._file_size:
            self._tracker.mark_exhausted("bytes")
        return data

    def readinto(self, buffer: bytearray | memoryview) -> int:
        data = self.read(len(buffer))
        size = len(data)
        buffer[:size] = data
        return size

    def close(self) -> None:
        if not self.closed:
            try:
                self._stream.close()
            finally:
                super().close()

    @property
    def mode(self) -> str:
        return "rb"

    @property
    def name(self) -> str:
        return str(getattr(self._stream, "name", "<source-inspection>"))
