from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DatabaseClassification(str, Enum):
    EMPTY = "EMPTY"
    UNVERSIONED_LEGACY_MATCH = "UNVERSIONED_LEGACY_MATCH"
    UNVERSIONED_LEGACY_MISMATCH = "UNVERSIONED_LEGACY_MISMATCH"
    VERSIONED = "VERSIONED"
    VERSIONED_INVALID = "VERSIONED_INVALID"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str
    migration_type: str
    sql: str

    @property
    def identifier(self) -> str:
        return f"{self.version:04d}_{self.name}"


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str


@dataclass(frozen=True, slots=True)
class DatabaseState:
    classification: DatabaseClassification
    current_version: int
    code_version: int
    database_server_version_num: int
    applied: tuple[AppliedMigration, ...] = ()
    pending: tuple[Migration, ...] = ()
    differences: tuple[str, ...] = ()
    summary: str = ""

    @property
    def is_strictly_current(self) -> bool:
        return (
            self.classification is DatabaseClassification.VERSIONED
            and self.current_version == self.code_version
            and not self.pending
        )
