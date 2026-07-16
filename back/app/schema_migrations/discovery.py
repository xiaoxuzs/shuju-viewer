from __future__ import annotations

import re
from pathlib import Path

from .errors import MigrationDiscoveryError
from .models import Migration
from .sql import migration_checksum, normalize_migration_bytes, validate_transactional_sql


MIGRATION_FILENAME_RE = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z][a-z0-9_]*)\.sql$")
HISTORICAL_SQL_ALLOWLIST = frozenset({"20260522_bu_identification_match_indexes.sql"})
_DECLARATION_RE = re.compile(r"^--\s*viewer-migration:\s*(?P<kind>[a-z][a-z0-9_-]*)\s*$")
_SUPPORTED_MIGRATION_TYPES = frozenset({"transactional"})


def _load_migration(path: Path, version: int, name: str) -> Migration:
    raw = path.read_bytes()
    normalized = normalize_migration_bytes(raw)
    sql = normalized.decode("utf-8")
    first_nonempty = next((line.strip() for line in sql.splitlines() if line.strip()), "")
    declaration = _DECLARATION_RE.fullmatch(first_nonempty)
    if declaration is None:
        raise MigrationDiscoveryError(
            f"migration {path.name} must begin with '-- viewer-migration: transactional'"
        )
    migration_type = declaration.group("kind")
    if migration_type not in _SUPPORTED_MIGRATION_TYPES:
        raise MigrationDiscoveryError(f"migration {path.name} has unsupported type: {migration_type}")
    validate_transactional_sql(sql)
    return Migration(
        version=version,
        name=name,
        path=path,
        checksum=migration_checksum(raw),
        migration_type=migration_type,
        sql=sql,
    )


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise MigrationDiscoveryError(f"migration directory does not exist: {directory}")

    migrations: list[Migration] = []
    versions: set[int] = set()
    names: set[str] = set()
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix.casefold() != ".sql":
            continue
        if path.name in HISTORICAL_SQL_ALLOWLIST:
            continue
        match = MIGRATION_FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise MigrationDiscoveryError(f"unexpected SQL file in migration directory: {path.name}")

        version = int(match.group("version"))
        name = match.group("name")
        if version == 0:
            raise MigrationDiscoveryError(f"migration version must be positive: {path.name}")
        if version in versions:
            raise MigrationDiscoveryError(f"duplicate migration version: {version:04d}")
        if name in names:
            raise MigrationDiscoveryError(f"duplicate migration name: {name}")
        versions.add(version)
        names.add(name)
        migrations.append(_load_migration(path, version, name))

    if not migrations:
        raise MigrationDiscoveryError("no versioned migration files were found")
    migrations.sort(key=lambda migration: migration.version)
    actual = [migration.version for migration in migrations]
    expected = list(range(1, len(migrations) + 1))
    if actual != expected:
        raise MigrationDiscoveryError(
            f"migration versions must be continuous from 0001: expected {expected}, found {actual}"
        )
    return tuple(migrations)
