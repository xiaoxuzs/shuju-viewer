from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIGURATION = 2
    CONNECTION = 3
    SCHEMA_STATE = 4
    LOCK_TIMEOUT = 5
    MIGRATION_TRANSACTION = 6


class SchemaMigrationError(RuntimeError):
    exit_code = ExitCode.SCHEMA_STATE


class ConfigurationError(SchemaMigrationError):
    exit_code = ExitCode.CONFIGURATION


class ConnectionTargetError(SchemaMigrationError):
    exit_code = ExitCode.CONNECTION


class SchemaStateError(SchemaMigrationError):
    exit_code = ExitCode.SCHEMA_STATE


class MigrationDiscoveryError(SchemaStateError):
    pass


class SqlSafetyError(MigrationDiscoveryError):
    pass


class MigrationLockTimeout(SchemaMigrationError):
    exit_code = ExitCode.LOCK_TIMEOUT


class MigrationTransactionError(SchemaMigrationError):
    exit_code = ExitCode.MIGRATION_TRANSACTION
