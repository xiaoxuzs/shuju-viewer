from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

from .catalog import (
    baseline_catalog,
    catalog_differences,
    catalog_is_empty,
    collect_catalog_in_transaction,
    load_legacy_baseline,
)
from .discovery import discover_migrations
from .errors import (
    ConfigurationError,
    ConnectionTargetError,
    MigrationLockTimeout,
    MigrationTransactionError,
    SchemaStateError,
)
from .models import AppliedMigration, DatabaseClassification, DatabaseState, Migration
from .sql import normalize_catalog_sql


PACKAGE_DIRECTORY = Path(__file__).resolve().parent
BACKEND_DIRECTORY = PACKAGE_DIRECTORY.parents[1]
REPOSITORY_DIRECTORY = BACKEND_DIRECTORY.parent
DEFAULT_MIGRATION_DIRECTORY = BACKEND_DIRECTORY / "migrations"
DEFAULT_BASELINE_PATH = DEFAULT_MIGRATION_DIRECTORY / "legacy_baseline_v1.json"
DEFAULT_PYPROJECT_PATH = BACKEND_DIRECTORY / "pyproject.toml"

DATABASE_URL_ENV = "VIEWER_SCHEMA_DATABASE_URL"
APPLIED_BY_ENV = "VIEWER_SCHEMA_APPLIED_BY"
ADVISORY_LOCK_MATERIAL = b"viewer:schema-migrations:v1"
GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_TIMEOUT_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min)\Z")


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    dsn: str
    redacted: str


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    migration_directory: Path = DEFAULT_MIGRATION_DIRECTORY
    baseline_path: Path = DEFAULT_BASELINE_PATH
    pyproject_path: Path = DEFAULT_PYPROJECT_PATH
    repository_directory: Path = REPOSITORY_DIRECTORY
    advisory_lock_timeout_seconds: float = 30.0
    advisory_lock_poll_seconds: float = 0.25
    lock_timeout: str = "5s"
    statement_timeout: str = "60s"

    def validate(self) -> None:
        if self.advisory_lock_timeout_seconds < 0:
            raise ConfigurationError("advisory lock timeout must be non-negative")
        if self.advisory_lock_poll_seconds <= 0:
            raise ConfigurationError("advisory lock poll interval must be positive")
        if _TIMEOUT_RE.fullmatch(self.lock_timeout) is None:
            raise ConfigurationError("lock_timeout must be a positive PostgreSQL duration")
        if _TIMEOUT_RE.fullmatch(self.statement_timeout) is None:
            raise ConfigurationError("statement_timeout must be a positive PostgreSQL duration")


def advisory_lock_key() -> int:
    unsigned = int.from_bytes(hashlib.sha256(ADVISORY_LOCK_MATERIAL).digest()[:8], "big", signed=False)
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


def _render_host(parts: Any) -> str:
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return host


def validate_database_url(value: str) -> DatabaseTarget:
    raw = value.strip()
    if not raw:
        raise ConfigurationError(f"database URL is required via --database-url or {DATABASE_URL_ENV}")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise ConnectionTargetError("invalid PostgreSQL URL") from exc
    if parts.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ConnectionTargetError("database URL must use PostgreSQL with psycopg")
    if not parts.hostname:
        raise ConnectionTargetError("PostgreSQL URL must contain an explicit host")
    database_name = parts.path.removeprefix("/")
    if not database_name or "/" in database_name:
        raise ConnectionTargetError("PostgreSQL URL must contain one explicit database name")
    if parts.fragment:
        raise ConnectionTargetError("PostgreSQL URL fragments are not supported")

    scheme = "postgresql"
    username = quote(unquote(parts.username or ""), safe="")
    userinfo = username
    if parts.password is not None:
        userinfo = f"{userinfo}:{quote(unquote(parts.password), safe='')}"
    host = _render_host(parts)
    authority = f"{userinfo}@{host}" if userinfo else host
    if port is not None:
        authority = f"{authority}:{port}"
    dsn = urlunsplit((scheme, authority, parts.path, parts.query, ""))

    redacted_userinfo = username
    if parts.password is not None:
        redacted_userinfo = f"{redacted_userinfo}:***"
    redacted_authority = f"{redacted_userinfo}@{host}" if redacted_userinfo else host
    if port is not None:
        redacted_authority = f"{redacted_authority}:{port}"
    redacted_query = "&".join(f"{quote(key, safe='')}=***" for key, _value in parse_qsl(parts.query, keep_blank_values=True))
    redacted = urlunsplit((scheme, redacted_authority, parts.path, redacted_query, ""))
    return DatabaseTarget(dsn=dsn, redacted=redacted)


def resolve_database_url(cli_value: str | None, env: Mapping[str, str] | None = None) -> DatabaseTarget:
    source = os.environ if env is None else env
    value = cli_value if cli_value is not None and cli_value.strip() else source.get(DATABASE_URL_ENV, "")
    return validate_database_url(value)


def validate_applied_by(value: str | None) -> str:
    applied_by = (value or "").strip()
    if not applied_by:
        raise ConfigurationError(f"upgrade requires --applied-by or {APPLIED_BY_ENV}")
    if "://" in applied_by or applied_by.casefold().startswith(("postgresql:", "postgres:")):
        raise ConfigurationError("applied_by must identify an operator, not a URL")
    if "\x00" in applied_by:
        raise ConfigurationError("applied_by contains an invalid character")
    return applied_by


def resolve_applied_by(cli_value: str | None, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = cli_value if cli_value is not None and cli_value.strip() else source.get(APPLIED_BY_ENV)
    return validate_applied_by(value)


def read_application_version(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        version = data["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"cannot read application version from {path.name}") from exc
    if not isinstance(version, str) or not version.strip():
        raise ConfigurationError(f"application version in {path.name} is invalid")
    return version.strip()


def read_git_commit(repository_directory: Path) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "git commit could not be determined; migration record will store NULL"
    commit = result.stdout.strip()
    if result.returncode != 0 or GIT_COMMIT_RE.fullmatch(commit) is None:
        return None, "git commit could not be validated; migration record will store NULL"
    return commit, None


def _connect(target: DatabaseTarget) -> Any:
    try:
        import psycopg

        return psycopg.connect(target.dsn, autocommit=True)
    except Exception as exc:
        raise ConnectionTargetError(f"could not connect to PostgreSQL target {target.redacted}") from exc


def _server_version(connection: Any) -> int:
    try:
        value = connection.execute(
            "SELECT current_setting('server_version_num')::integer"
        ).fetchone()[0]
    except Exception as exc:
        raise ConnectionTargetError("could not read PostgreSQL server version") from exc
    version = int(value)
    if version // 10000 != 16:
        raise ConnectionTargetError("PostgreSQL 16 is required for schema migration operations")
    return version


def _simplify_constraint_definition(value: str) -> str:
    normalized = normalize_catalog_sql(value) or ""
    normalized = normalized.replace("::text", "").replace("::character varying", "")
    return re.sub(r"[()\s]", "", normalized)


_VERSION_COLUMNS = (
    ("version", "integer", True, None),
    ("name", "character varying(200)", True, None),
    ("checksum", "character varying(64)", True, None),
    ("applied_at", "timestamp with time zone", True, "clock_timestamp()"),
    ("applied_by", "text", True, None),
    ("execution_ms", "bigint", True, None),
    ("application_version", "text", True, None),
    ("git_commit", "character varying(64)", False, None),
    ("database_server_version_num", "integer", True, None),
)

_VERSION_CONSTRAINTS = {
    "schema_migrations_pkey": ("p", "PRIMARY KEY (version)"),
    "schema_migrations_name_key": ("u", "UNIQUE (name)"),
    "ck_schema_migrations_version": ("c", "CHECK (version > 0)"),
    "ck_schema_migrations_checksum": ("c", "CHECK (checksum ~ '^[0-9a-f]{64}$')"),
    "ck_schema_migrations_applied_by": ("c", "CHECK (btrim(applied_by) <> '')"),
    "ck_schema_migrations_execution_ms": ("c", "CHECK (execution_ms >= 0)"),
    "ck_schema_migrations_application_version": ("c", "CHECK (btrim(application_version) <> '')"),
    "ck_schema_migrations_git_commit": (
        "c",
        "CHECK (git_commit IS NULL OR git_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$')",
    ),
    "ck_schema_migrations_server_version": ("c", "CHECK (database_server_version_num > 0)"),
}

_VERSION_TRIGGERS = {
    "schema_migrations_reject_update_delete": (
        "CREATE TRIGGER schema_migrations_reject_update_delete BEFORE UPDATE OR DELETE ON "
        "public.schema_migrations FOR EACH STATEMENT EXECUTE FUNCTION "
        "public.schema_migrations_reject_mutation()"
    ),
    "schema_migrations_reject_truncate": (
        "CREATE TRIGGER schema_migrations_reject_truncate BEFORE TRUNCATE ON public.schema_migrations "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.schema_migrations_reject_mutation()"
    ),
}


def _versioning_object_differences(catalog: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    relation = [row for row in catalog["relations"] if row["name"] == "schema_migrations"]
    if relation != [
        {"name": "schema_migrations", "relkind": "r", "relpersistence": "p", "is_partition": False}
    ]:
        differences.append("public.schema_migrations relation definition is invalid")

    actual_columns = [
        (row["name"], row["format_type"], row["not_null"], row["default"])
        for row in catalog["columns"]
        if row["relation"] == "schema_migrations"
    ]
    if tuple(actual_columns) != _VERSION_COLUMNS:
        differences.append("public.schema_migrations column definition is invalid")

    actual_constraints = {
        row["name"]: (row["contype"], _simplify_constraint_definition(row["definition"]))
        for row in catalog["constraints"]
        if row["relation"] == "schema_migrations"
    }
    expected_constraints = {
        name: (kind, _simplify_constraint_definition(definition))
        for name, (kind, definition) in _VERSION_CONSTRAINTS.items()
    }
    if actual_constraints != expected_constraints:
        differences.append("public.schema_migrations constraints are invalid")

    actual_indexes = {
        row["name"]: (row["unique"], row["primary"], row["valid"], row["ready"], row["method"])
        for row in catalog["indexes"]
        if row["relation"] == "schema_migrations"
    }
    expected_indexes = {
        "schema_migrations_pkey": (True, True, True, True, "btree"),
        "schema_migrations_name_key": (True, False, True, True, "btree"),
    }
    if actual_indexes != expected_indexes:
        differences.append("public.schema_migrations indexes are invalid")

    functions = [row for row in catalog["functions"] if row["name"] == "schema_migrations_reject_mutation"]
    if len(functions) != 1:
        differences.append("append-only protection function is missing or ambiguous")
    else:
        function = functions[0]
        definition = normalize_catalog_sql(function["definition"]) or ""
        required = (
            function["kind"] == "f",
            function["identity_arguments"] == "",
            function["return_type"] == "trigger",
            function["volatile"] == "v",
            function["security_definer"] is False,
            function["language"] == "plpgsql",
            "public.schema_migrations is append-only: % is not allowed" in definition,
            "TG_OP" in definition,
            "ERRCODE = '55000'" in definition,
        )
        if not all(required):
            differences.append("append-only protection function definition is invalid")

    actual_triggers = {
        row["name"]: (row["enabled"], normalize_catalog_sql(row["definition"]))
        for row in catalog["triggers"]
        if row["relation"] == "schema_migrations"
    }
    expected_triggers = {name: ("O", definition) for name, definition in _VERSION_TRIGGERS.items()}
    if actual_triggers != expected_triggers:
        differences.append("append-only protection triggers are invalid")
    return differences


def _history_differences(
    applied: Sequence[AppliedMigration], migrations: Sequence[Migration]
) -> tuple[list[str], tuple[Migration, ...]]:
    differences: list[str] = []
    if not applied:
        return ["schema_migrations has no 0001 history row"], ()
    versions = [row.version for row in applied]
    expected_versions = list(range(1, max(versions) + 1))
    if versions != expected_versions:
        differences.append(f"database migration versions are not continuous: {versions}")

    by_version = {migration.version: migration for migration in migrations}
    code_version = migrations[-1].version
    if max(versions) > code_version:
        differences.append(
            f"database migration version {max(versions):04d} is higher than code version {code_version:04d}"
        )
    for row in applied:
        migration = by_version.get(row.version)
        if migration is None:
            differences.append(f"database contains unknown migration version {row.version:04d}")
            continue
        if row.name != migration.name:
            differences.append(f"migration {row.version:04d} name differs from code")
        if row.checksum != migration.checksum:
            differences.append(f"migration {row.version:04d} checksum differs from code")
    current = max(versions)
    pending = tuple(migration for migration in migrations if migration.version > current)
    return differences, pending


def read_database_state(
    connection: Any,
    migrations: Sequence[Migration],
    baseline: Mapping[str, Any],
) -> DatabaseState:
    code_version = migrations[-1].version
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        server_version = _server_version(connection)
        version_table_exists = bool(
            connection.execute(
                "SELECT pg_catalog.to_regclass('public.schema_migrations') IS NOT NULL"
            ).fetchone()[0]
        )
        catalog = collect_catalog_in_transaction(connection)

        if version_table_exists:
            differences = _versioning_object_differences(catalog)
            applied: tuple[AppliedMigration, ...] = ()
            pending: tuple[Migration, ...] = ()
            if not differences:
                try:
                    rows = connection.execute(
                        "SELECT version, name, checksum FROM public.schema_migrations ORDER BY version"
                    ).fetchall()
                    applied = tuple(AppliedMigration(int(row[0]), str(row[1]), str(row[2])) for row in rows)
                except Exception:
                    differences.append("schema_migrations history could not be read")
                if not differences:
                    history_differences, pending = _history_differences(applied, migrations)
                    differences.extend(history_differences)
            current = max((row.version for row in applied), default=0)
            if differences:
                return DatabaseState(
                    classification=DatabaseClassification.VERSIONED_INVALID,
                    current_version=current,
                    code_version=code_version,
                    database_server_version_num=server_version,
                    applied=applied,
                    differences=tuple(differences[:12]),
                    summary="version table, protection objects, or migration history is invalid",
                )
            return DatabaseState(
                classification=DatabaseClassification.VERSIONED,
                current_version=current,
                code_version=code_version,
                database_server_version_num=server_version,
                applied=applied,
                pending=pending,
                summary="versioned migration history is valid",
            )

        if catalog_is_empty(catalog):
            return DatabaseState(
                classification=DatabaseClassification.EMPTY,
                current_version=0,
                code_version=code_version,
                database_server_version_num=server_version,
                summary="public has no Viewer schema objects",
            )

        differences = catalog_differences(baseline_catalog(baseline), catalog)
        if differences:
            return DatabaseState(
                classification=DatabaseClassification.UNVERSIONED_LEGACY_MISMATCH,
                current_version=0,
                code_version=code_version,
                database_server_version_num=server_version,
                differences=differences,
                summary="unversioned public catalog does not match legacy_baseline_v1",
            )
        return DatabaseState(
            classification=DatabaseClassification.UNVERSIONED_LEGACY_MATCH,
            current_version=0,
            code_version=code_version,
            database_server_version_num=server_version,
            pending=tuple(migrations),
            summary="unversioned public catalog exactly matches legacy_baseline_v1",
        )


def _load_inputs(config: RunnerConfig) -> tuple[tuple[Migration, ...], dict[str, Any]]:
    config.validate()
    return discover_migrations(config.migration_directory), load_legacy_baseline(config.baseline_path)


def inspect_database(target: DatabaseTarget, config: RunnerConfig = RunnerConfig()) -> DatabaseState:
    migrations, baseline = _load_inputs(config)
    connection = _connect(target)
    try:
        return read_database_state(connection, migrations, baseline)
    except (SchemaStateError, ConnectionTargetError):
        raise
    except Exception as exc:
        raise ConnectionTargetError(f"could not inspect PostgreSQL target {target.redacted}") from exc
    finally:
        connection.close()


def require_strict_check(state: DatabaseState) -> None:
    if not state.is_strictly_current:
        detail = f": {state.differences[0]}" if state.differences else ""
        raise SchemaStateError(
            f"strict schema check failed with {state.classification.value}{detail}"
        )


def check_database(target: DatabaseTarget, config: RunnerConfig = RunnerConfig()) -> DatabaseState:
    state = inspect_database(target, config)
    require_strict_check(state)
    return state


def plan_database(target: DatabaseTarget, config: RunnerConfig = RunnerConfig()) -> DatabaseState:
    state = inspect_database(target, config)
    if state.classification not in {
        DatabaseClassification.UNVERSIONED_LEGACY_MATCH,
        DatabaseClassification.VERSIONED,
    }:
        detail = f": {state.differences[0]}" if state.differences else ""
        raise SchemaStateError(f"migration plan refused for {state.classification.value}{detail}")
    return state


def _acquire_advisory_lock(connection: Any, config: RunnerConfig) -> None:
    deadline = time.monotonic() + config.advisory_lock_timeout_seconds
    key = advisory_lock_key()
    while True:
        if bool(connection.execute("SELECT pg_catalog.pg_try_advisory_lock(%s)", (key,)).fetchone()[0]):
            return
        if time.monotonic() >= deadline:
            raise MigrationLockTimeout(
                f"timed out after {config.advisory_lock_timeout_seconds:g}s waiting for schema migration lock"
            )
        time.sleep(min(config.advisory_lock_poll_seconds, max(0.0, deadline - time.monotonic())))


def _release_advisory_lock(connection: Any) -> None:
    connection.execute("SELECT pg_catalog.pg_advisory_unlock(%s)", (advisory_lock_key(),))


def _execute_one_migration(
    connection: Any,
    migration: Migration,
    *,
    applied_by: str,
    application_version: str,
    git_commit: str | None,
    config: RunnerConfig,
) -> None:
    started = time.monotonic()
    try:
        with connection.transaction():
            connection.execute(f"SET LOCAL lock_timeout = '{config.lock_timeout}'")
            connection.execute(f"SET LOCAL statement_timeout = '{config.statement_timeout}'")
            connection.execute(migration.sql, prepare=False)
            execution_ms = max(0, int((time.monotonic() - started) * 1000))
            server_version = int(
                connection.execute(
                    "SELECT current_setting('server_version_num')::integer"
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO public.schema_migrations (
                    version, name, checksum, applied_by, execution_ms,
                    application_version, git_commit, database_server_version_num
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    applied_by,
                    execution_ms,
                    application_version,
                    git_commit,
                    server_version,
                ),
            )
    except Exception as exc:
        raise MigrationTransactionError(
            f"migration {migration.identifier} failed; its transaction was rolled back ({type(exc).__name__})"
        ) from exc


def upgrade_database(
    target: DatabaseTarget,
    *,
    applied_by: str,
    config: RunnerConfig = RunnerConfig(),
) -> tuple[DatabaseState, str | None]:
    migrations, baseline = _load_inputs(config)
    operator = validate_applied_by(applied_by)
    application_version = read_application_version(config.pyproject_path)
    git_commit, git_hint = read_git_commit(config.repository_directory)
    connection = _connect(target)
    lock_acquired = False
    try:
        _acquire_advisory_lock(connection, config)
        lock_acquired = True

        # This classification is deliberately performed only after the session lock is held.
        state = read_database_state(connection, migrations, baseline)
        if state.classification not in {
            DatabaseClassification.UNVERSIONED_LEGACY_MATCH,
            DatabaseClassification.VERSIONED,
        }:
            detail = f": {state.differences[0]}" if state.differences else ""
            raise SchemaStateError(f"upgrade refused for {state.classification.value}{detail}")

        for migration in state.pending:
            _execute_one_migration(
                connection,
                migration,
                applied_by=operator,
                application_version=application_version,
                git_commit=git_commit,
                config=config,
            )

        final_state = read_database_state(connection, migrations, baseline)
        try:
            require_strict_check(final_state)
        except SchemaStateError as exc:
            raise SchemaStateError(
                "migrations committed, but the final strict check failed; committed history was not modified: "
                f"{exc}"
            ) from exc
        return final_state, git_hint
    finally:
        if lock_acquired:
            try:
                _release_advisory_lock(connection)
            except Exception:
                pass
        connection.close()
