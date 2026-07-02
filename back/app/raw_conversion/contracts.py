"""Small data contracts for Thermo RAW conversion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RAW_VENDOR_THERMO = "thermo"
RAW_CONVERSION_STATUSES = ("converted", "skipped_existing_mzml", "failed")
RawConversionStatus = Literal["converted", "skipped_existing_mzml", "failed"]


@dataclass(frozen=True)
class RawFileCandidate:
    raw_path: Path
    stem: str
    vendor: str
    expected_mzml_path: Path
    existing_mzml_path: Path | None = None


@dataclass(frozen=True)
class RawConversionRequest:
    raw_path: Path
    output_dir: Path
    converter_exe: Path | None
    timeout_seconds: int
    force: bool = False


@dataclass(frozen=True)
class RawConversionResult:
    raw_path: Path
    mzml_path: Path | None
    status: RawConversionStatus
    converter_name: str
    converter_version: str | None
    command: list[str]
    started_at: str | None
    finished_at: str | None
    stdout_log_path: Path | None
    stderr_log_path: Path | None
    error_message: str | None = None

    def metadata(self) -> dict[str, object | None]:
        return {
            "converter_name": self.converter_name,
            "converter_version": self.converter_version,
            "status": self.status,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stdout_log_path": str(self.stdout_log_path) if self.stdout_log_path is not None else None,
            "stderr_log_path": str(self.stderr_log_path) if self.stderr_log_path is not None else None,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class RawConversionBatch:
    results: tuple[RawConversionResult, ...]
    raw_to_mzml: dict[str, Path]

    @property
    def total_raw_files(self) -> int:
        return len(self.results)

    def summary(self) -> dict[str, int]:
        converted = sum(1 for r in self.results if r.status == "converted")
        skipped = sum(1 for r in self.results if r.status == "skipped_existing_mzml")
        failed = sum(1 for r in self.results if r.status == "failed")
        return {
            "total_raw_files": len(self.results),
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
        }
