from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from app.schema_migrations import runner
from app.schema_migrations.catalog import (
    CATALOG_COLLECTIONS,
    EXPECTED_EXCLUDED_DIMENSIONS,
    baseline_catalog,
    canonicalize_catalog,
    catalog_differences,
    collect_catalog,
    load_legacy_baseline,
)
from app.schema_migrations.discovery import discover_migrations
from app.schema_migrations.errors import (
    ConfigurationError,
    MigrationDiscoveryError,
    MigrationTransactionError,
    SqlSafetyError,
)
from app.schema_migrations.models import AppliedMigration, DatabaseClassification, Migration
from app.schema_migrations.runner import (
    RunnerConfig,
    _execute_one_migration,
    _history_differences,
    advisory_lock_key,
    read_application_version,
    read_database_state,
    read_git_commit,
    resolve_database_url,
    upgrade_database,
    validate_database_url,
)
from app.schema_migrations.sql import migration_checksum, validate_transactional_sql


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = BACKEND_ROOT / "migrations"
BASELINE = MIGRATIONS / "legacy_baseline_v1.json"
DECLARATION = "-- viewer-migration: transactional\n"


def _write_migration(directory: Path, name: str, sql: str = "SELECT 1;\n") -> Path:
    path = directory / name
    path.write_text(f"{DECLARATION}{sql}", encoding="utf-8", newline="")
    return path


def _migration(version: int = 1, name: str = "schema_migrations", checksum: str = "a" * 64) -> Migration:
    return Migration(
        version=version,
        name=name,
        path=Path(f"{version:04d}_{name}.sql"),
        checksum=checksum,
        migration_type="transactional",
        sql=f"{DECLARATION}SELECT {version};\n",
    )


def _empty_catalog() -> dict[str, object]:
    return {"schema_name": "public", **{name: [] for name in CATALOG_COLLECTIONS}}


def test_discovers_valid_migration_and_only_exact_historical_sql_is_ignored(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_schema_migrations.sql")
    (tmp_path / "20260522_bu_identification_match_indexes.sql").write_text("historical", encoding="utf-8")
    migrations = discover_migrations(tmp_path)

    assert [(item.version, item.name) for item in migrations] == [(1, "schema_migrations")]


@pytest.mark.parametrize("filename", ["notes.sql", "20260716_unknown.sql", "0001_Bad.sql", "00001_bad.sql"])
def test_rejects_every_other_invalid_sql_filename(tmp_path: Path, filename: str) -> None:
    _write_migration(tmp_path, "0001_schema_migrations.sql")
    (tmp_path / filename).write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError, match="unexpected SQL file"):
        discover_migrations(tmp_path)


def test_rejects_duplicate_version(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_first.sql")
    _write_migration(tmp_path, "0001_second.sql")

    with pytest.raises(MigrationDiscoveryError, match="duplicate migration version"):
        discover_migrations(tmp_path)


def test_rejects_duplicate_name(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_same.sql")
    _write_migration(tmp_path, "0002_same.sql")

    with pytest.raises(MigrationDiscoveryError, match="duplicate migration name"):
        discover_migrations(tmp_path)


def test_rejects_missing_version(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_first.sql")
    _write_migration(tmp_path, "0003_third.sql")

    with pytest.raises(MigrationDiscoveryError, match="continuous"):
        discover_migrations(tmp_path)


def test_lf_crlf_and_cr_have_the_same_checksum() -> None:
    lf = b"-- viewer-migration: transactional\nSELECT 1;\n"
    assert migration_checksum(lf) == migration_checksum(lf.replace(b"\n", b"\r\n"))
    assert migration_checksum(lf) == migration_checksum(lf.replace(b"\n", b"\r"))


def test_checksum_does_not_trim_final_newline_or_spaces() -> None:
    base = b"-- viewer-migration: transactional\nSELECT 1;"
    assert migration_checksum(base) != migration_checksum(base + b"\n")
    assert migration_checksum(base) != migration_checksum(base + b" ")


def test_rejects_bom_and_non_utf8(tmp_path: Path) -> None:
    path = tmp_path / "0001_bad.sql"
    path.write_bytes(b"\xef\xbb\xbf" + DECLARATION.encode() + b"SELECT 1;")
    with pytest.raises(SqlSafetyError, match="BOM"):
        discover_migrations(tmp_path)

    path.write_bytes(b"\xff\xfe")
    with pytest.raises(SqlSafetyError, match="UTF-8"):
        discover_migrations(tmp_path)


def test_rejects_version_zero_and_unknown_migration_type(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0000_zero.sql")
    with pytest.raises(MigrationDiscoveryError, match="positive"):
        discover_migrations(tmp_path)

    (tmp_path / "0000_zero.sql").unlink()
    (tmp_path / "0001_bad.sql").write_text("-- viewer-migration: nontransactional\nSELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationDiscoveryError, match="unsupported type"):
        discover_migrations(tmp_path)


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("CREATE INDEX CONCURRENTLY idx ON t (id);", "CREATE INDEX CONCURRENTLY"),
        ("CREATE UNIQUE INDEX CONCURRENTLY idx ON t (id);", "CREATE UNIQUE INDEX CONCURRENTLY"),
        ("DROP INDEX CONCURRENTLY idx;", "DROP INDEX CONCURRENTLY"),
        ("REINDEX (VERBOSE) INDEX CONCURRENTLY idx;", "REINDEX CONCURRENTLY"),
        ("VACUUM t;", "VACUUM"),
        ("CREATE DATABASE nope;", "CREATE DATABASE"),
        ("DROP DATABASE nope;", "DROP DATABASE"),
        ("ALTER SYSTEM SET x = 'y';", "ALTER SYSTEM"),
        ("BEGIN;", "BEGIN"),
        ("START TRANSACTION;", "START TRANSACTION"),
        ("COMMIT;", "COMMIT"),
        ("ROLLBACK;", "ROLLBACK"),
    ],
)
def test_sql_scanner_rejects_forbidden_top_level_operations(sql: str, operation: str) -> None:
    with pytest.raises(SqlSafetyError, match=operation):
        validate_transactional_sql(sql)


def test_sql_scanner_ignores_keywords_in_comments_strings_identifiers_and_dollar_bodies() -> None:
    sql = """
    -- COMMIT and VACUUM
    /* outer DROP DATABASE x; /* nested ALTER SYSTEM */ still comment */
    CREATE TABLE public.probe (value text DEFAULT 'ROLLBACK; COMMIT');
    CREATE FUNCTION public.probe_fn() RETURNS void LANGUAGE plpgsql AS $body$
    BEGIN
        RAISE NOTICE 'CREATE INDEX CONCURRENTLY and COMMIT';
    END;
    $body$;
    SELECT "VACUUM" FROM public.probe;
    """

    validate_transactional_sql(sql)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 'unterminated", 'SELECT "unterminated', "SELECT $tag$unterminated", "/* unterminated"],
)
def test_sql_scanner_conservatively_rejects_unclosed_input(sql: str) -> None:
    with pytest.raises(SqlSafetyError, match="unterminated"):
        validate_transactional_sql(sql)


def test_history_rejects_name_checksum_ahead_and_gaps() -> None:
    migrations = (_migration(1), _migration(2, "second", "b" * 64))

    differences, _ = _history_differences((AppliedMigration(1, "renamed", "a" * 64),), migrations)
    assert any("name differs" in item for item in differences)
    differences, _ = _history_differences((AppliedMigration(1, "schema_migrations", "c" * 64),), migrations)
    assert any("checksum differs" in item for item in differences)
    differences, _ = _history_differences(
        (
            AppliedMigration(1, "schema_migrations", "a" * 64),
            AppliedMigration(2, "second", "b" * 64),
            AppliedMigration(3, "future", "c" * 64),
        ),
        migrations,
    )
    assert any("higher than code" in item for item in differences)
    differences, _ = _history_differences(
        (
            AppliedMigration(1, "schema_migrations", "a" * 64),
            AppliedMigration(3, "future", "c" * 64),
        ),
        migrations,
    )
    assert any("not continuous" in item for item in differences)


def test_url_validation_redacts_password_and_query_values() -> None:
    target = validate_database_url(
        "postgresql+psycopg://viewer:super-secret@db.example:5432/viewer?sslmode=require&token=hidden"
    )
    assert target.redacted == "postgresql://viewer:***@db.example:5432/viewer?sslmode=***&token=***"
    assert "super-secret" not in target.redacted
    assert "hidden" not in target.redacted


@pytest.mark.parametrize("url", ["", "sqlite:///x.db", "postgresql://host", "postgresql:///viewer"])
def test_url_validation_rejects_missing_or_non_postgresql_targets(url: str) -> None:
    with pytest.raises((ConfigurationError, runner.ConnectionTargetError)):
        validate_database_url(url)


def test_database_url_resolution_ignores_database_url_and_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("VIEWER_SCHEMA_DATABASE_URL=postgresql://user:secret@host/db\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError):
        resolve_database_url(None, {"DATABASE_URL": "postgresql://user:secret@host/db"})


def test_advisory_lock_key_is_stable_across_processes() -> None:
    code = "from app.schema_migrations.runner import advisory_lock_key; print(advisory_lock_key())"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )
    assert int(result.stdout.strip()) == advisory_lock_key() == 7989853075422222121


def test_application_version_is_required_and_never_invented(tmp_path: Path) -> None:
    valid = tmp_path / "pyproject.toml"
    valid.write_bytes(b'[project]\nversion = "2.3.4"\n')
    assert read_application_version(valid) == "2.3.4"

    invalid = tmp_path / "invalid.toml"
    invalid.write_bytes(b"[project]\n")
    with pytest.raises(ConfigurationError, match="cannot read application version"):
        read_application_version(invalid)
    with pytest.raises(ConfigurationError, match="cannot read application version"):
        read_application_version(tmp_path / "missing.toml")


def test_git_commit_uses_argument_array_cwd_timeout_and_no_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = "a" * 40 + "\n"

    def fake_run(command: object, **kwargs: object) -> Result:
        captured["command"] = command
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    commit, hint = read_git_commit(tmp_path)

    assert commit == "a" * 40
    assert hint is None
    assert captured["command"] == ["git", "rev-parse", "HEAD"]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 5
    assert captured["shell"] is False


def test_baseline_is_canonical_complete_and_has_every_required_dimension() -> None:
    baseline = load_legacy_baseline(BASELINE)
    catalog = baseline_catalog(baseline)

    assert baseline["object_counts"] == {
        "columns": 91,
        "constraints": 26,
        "functions": 0,
        "indexes": 31,
        "sequences": 7,
        "tables": 8,
        "triggers": 0,
    }
    assert len(catalog["relations"]) == 15
    assert tuple(baseline["excluded_dimensions"]) == EXPECTED_EXCLUDED_DIMENSIONS
    assert catalog["functions"] == []
    assert catalog["triggers"] == []
    dataset_id = next(
        column
        for column in catalog["columns"]
        if column["relation"] == "datasets" and column["name"] == "dataset_id"
    )
    assert dataset_id["default"] == "nextval('public.datasets_dataset_id_seq'::regclass)"
    assert all("owner" not in row and "acl" not in row and "comment" not in row for name in CATALOG_COLLECTIONS for row in catalog[name])
    assert all(
        required in baseline[collection][0]
        for collection, required in (
            ("columns", "ordinal_position"),
            ("constraints", "definition"),
            ("indexes", "predicate"),
            ("sequences", "owned_by_relation"),
        )
    )


def test_baseline_rejects_noncanonical_or_incomplete_json(tmp_path: Path) -> None:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    data["columns"].pop()
    path = tmp_path / "baseline.json"
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    with pytest.raises(runner.SchemaStateError, match="counts"):
        load_legacy_baseline(path)

    path.write_bytes(json.dumps(json.loads(BASELINE.read_text(encoding="utf-8"))).encode("utf-8"))
    with pytest.raises(runner.SchemaStateError, match="canonical"):
        load_legacy_baseline(path)


def test_baseline_canonical_form_accepts_windows_or_linux_line_endings(tmp_path: Path) -> None:
    raw = BASELINE.read_bytes()
    windows = tmp_path / "windows.json"
    windows.write_bytes(raw.replace(b"\n", b"\r\n"))
    assert load_legacy_baseline(windows)["baseline_id"] == "legacy_baseline_v1"


def test_catalog_sorting_and_structural_differences_are_deterministic() -> None:
    expected = baseline_catalog(load_legacy_baseline(BASELINE))
    shuffled = {"schema_name": "public"}
    randomizer = random.Random(42)
    for name in CATALOG_COLLECTIONS:
        shuffled[name] = list(expected[name])
        randomizer.shuffle(shuffled[name])
    assert canonicalize_catalog(shuffled) == expected

    changed = json.loads(json.dumps(expected))
    changed["columns"][0]["format_type"] = "integer"
    differences = catalog_differences(expected, changed)
    assert differences == (
        "columns('datasets', 1).format_type differs: expected='bigint' actual='integer'",
    )


def test_catalog_comparison_does_not_relax_schema_qualified_defaults() -> None:
    expected = baseline_catalog(load_legacy_baseline(BASELINE))
    actual = json.loads(json.dumps(expected))
    dataset_id = next(
        column
        for column in actual["columns"]
        if column["relation"] == "datasets" and column["name"] == "dataset_id"
    )
    dataset_id["default"] = "nextval('datasets_dataset_id_seq'::regclass)"

    assert catalog_differences(expected, actual) == (
        "columns('datasets', 1).default differs: "
        "expected=\"nextval('public.datasets_dataset_id_seq'::regclass)\" "
        "actual=\"nextval('datasets_dataset_id_seq'::regclass)\"",
    )


class _Result:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...]:
        return self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _CatalogConnection:
    def __init__(self, *, fail_search_path: bool = False) -> None:
        self.fail_search_path = fail_search_path
        self.calls: list[tuple[str, object]] = []

    def transaction(self) -> nullcontext[None]:
        return nullcontext()

    def execute(self, sql: str, params: object = None) -> _Result:
        self.calls.append((sql, params))
        if "set_config" in sql and self.fail_search_path:
            raise RuntimeError("cannot set transaction-local search_path")
        return _Result()


def test_catalog_sampling_sets_exact_transaction_local_search_path_before_deparsing() -> None:
    connection = _CatalogConnection()

    assert collect_catalog(connection) == _empty_catalog()

    assert connection.calls[0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        None,
    )
    search_path_sql, search_path_params = connection.calls[1]
    assert "pg_catalog.set_config('search_path', %s, true)" in " ".join(search_path_sql.split())
    assert search_path_params == ("pg_catalog",)

    deparser_positions = [
        position
        for position, (sql, _params) in enumerate(connection.calls)
        if "pg_get_" in sql or "format_type(" in sql
    ]
    assert deparser_positions
    assert all(position > 1 for position in deparser_positions)

    catalog_calls = connection.calls[2:]
    assert catalog_calls
    assert all(params == ("public",) for _sql, params in catalog_calls)
    all_sql = "\n".join(sql.upper() for sql, _params in connection.calls)
    assert "SHOW SEARCH_PATH" not in all_sql
    assert "ALTER DATABASE" not in all_sql
    assert "ALTER ROLE" not in all_sql
    assert "SET SEARCH_PATH" not in all_sql


def test_catalog_sampling_propagates_search_path_failure_before_catalog_queries() -> None:
    connection = _CatalogConnection(fail_search_path=True)

    with pytest.raises(RuntimeError, match="transaction-local search_path"):
        collect_catalog(connection)

    assert len(connection.calls) == 2
    assert "set_config" in connection.calls[-1][0]


class _StateConnection:
    def __init__(self, *, version_table_exists: bool, history: list[tuple[object, ...]] | None = None) -> None:
        self.version_table_exists = version_table_exists
        self.history = history or []

    def transaction(self) -> nullcontext[None]:
        return nullcontext()

    def execute(self, sql: str, _params: object = None, **_kwargs: object) -> _Result:
        if "server_version_num" in sql:
            return _Result([(160014,)])
        if "to_regclass" in sql:
            return _Result([(self.version_table_exists,)])
        if "SELECT version, name, checksum" in sql:
            return _Result(self.history)
        return _Result()


def test_classification_checks_version_table_before_legacy_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _migration()
    connection = _StateConnection(
        version_table_exists=True,
        history=[(1, migration.name, migration.checksum)],
    )
    monkeypatch.setattr(runner, "collect_catalog_in_transaction", lambda _connection: {"versioned": True})
    monkeypatch.setattr(runner, "_versioning_object_differences", lambda _catalog: [])
    monkeypatch.setattr(runner, "baseline_catalog", lambda _baseline: pytest.fail("legacy baseline was consulted"))

    state = read_database_state(connection, (migration,), {})

    assert state.classification is DatabaseClassification.VERSIONED


@pytest.mark.parametrize(
    ("empty", "differences", "classification"),
    [
        (True, (), DatabaseClassification.EMPTY),
        (False, (), DatabaseClassification.UNVERSIONED_LEGACY_MATCH),
        (False, ("relations('extra',) is unexpected",), DatabaseClassification.UNVERSIONED_LEGACY_MISMATCH),
    ],
)
def test_unversioned_classification_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    empty: bool,
    differences: tuple[str, ...],
    classification: DatabaseClassification,
) -> None:
    connection = _StateConnection(version_table_exists=False)
    catalog = _empty_catalog()
    monkeypatch.setattr(runner, "collect_catalog_in_transaction", lambda _connection: catalog)
    monkeypatch.setattr(runner, "catalog_is_empty", lambda _catalog: empty)
    monkeypatch.setattr(runner, "baseline_catalog", lambda _baseline: catalog)
    monkeypatch.setattr(runner, "catalog_differences", lambda _expected, _actual: differences)

    state = read_database_state(connection, (_migration(),), {})

    assert state.classification is classification


class _ExecuteConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def transaction(self) -> nullcontext[None]:
        return nullcontext()

    def execute(self, sql: str, params: object = None, *, prepare: object = None) -> _Result:
        self.calls.append((sql, params, prepare))
        if "server_version_num" in sql:
            return _Result([(160014,)])
        return _Result()


def test_executor_sends_complete_migration_text_once_without_semicolon_splitting(tmp_path: Path) -> None:
    sql = f"""{DECLARATION}
    CREATE FUNCTION public.f() RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM 1;
        PERFORM 2;
    END;
    $$;
    CREATE TABLE public.after_function (id integer);
    """
    migration = Migration(2, "function_probe", tmp_path / "0002_function_probe.sql", "b" * 64, "transactional", sql)
    connection = _ExecuteConnection()

    _execute_one_migration(
        connection,
        migration,
        applied_by="unit-test",
        application_version="0.1.0",
        git_commit=None,
        config=RunnerConfig(),
    )

    full_sql_calls = [call for call in connection.calls if call[0] == sql]
    assert full_sql_calls == [(sql, None, False)]
    assert not any(call[0].strip() in {"PERFORM 1", "PERFORM 2"} for call in connection.calls)


def test_executor_wraps_transaction_failure_without_continuing() -> None:
    class FailingConnection(_ExecuteConnection):
        def execute(self, sql: str, params: object = None, *, prepare: object = None) -> _Result:
            if sql.startswith(DECLARATION):
                raise RuntimeError("database detail")
            return super().execute(sql, params, prepare=prepare)

    with pytest.raises(MigrationTransactionError, match="rolled back"):
        _execute_one_migration(
            FailingConnection(),
            _migration(),
            applied_by="unit-test",
            application_version="0.1.0",
            git_commit=None,
            config=RunnerConfig(),
        )


def test_upgrade_classifies_only_after_lock_and_reports_final_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    events: list[str] = []
    first = runner.DatabaseState(
        classification=DatabaseClassification.UNVERSIONED_LEGACY_MATCH,
        current_version=0,
        code_version=1,
        database_server_version_num=160014,
        pending=(migration,),
    )
    final = runner.DatabaseState(
        classification=DatabaseClassification.VERSIONED_INVALID,
        current_version=1,
        code_version=1,
        database_server_version_num=160014,
        differences=("protection trigger missing",),
    )
    states = iter((first, final))

    class Connection:
        def close(self) -> None:
            events.append("close")

    connection = Connection()
    monkeypatch.setattr(runner, "_load_inputs", lambda _config: ((migration,), {}))
    monkeypatch.setattr(runner, "read_application_version", lambda _path: "0.1.0")
    monkeypatch.setattr(runner, "read_git_commit", lambda _path: (None, None))
    monkeypatch.setattr(runner, "_connect", lambda _target: connection)
    monkeypatch.setattr(runner, "_acquire_advisory_lock", lambda _connection, _config: events.append("lock"))
    monkeypatch.setattr(runner, "_release_advisory_lock", lambda _connection: events.append("unlock"))

    def fake_state(_connection: object, _migrations: object, _baseline: object) -> runner.DatabaseState:
        events.append("classify")
        return next(states)

    monkeypatch.setattr(runner, "read_database_state", fake_state)
    monkeypatch.setattr(
        runner,
        "_execute_one_migration",
        lambda *_args, **_kwargs: events.append("execute-and-commit"),
    )

    with pytest.raises(runner.SchemaStateError, match="migrations committed, but the final strict check failed"):
        upgrade_database(
            runner.DatabaseTarget("postgresql://host/db", "postgresql://host/db"),
            applied_by="operator",
        )

    assert events == ["lock", "classify", "execute-and-commit", "classify", "unlock", "close"]


def test_import_has_no_database_config_or_dotenv_side_effects() -> None:
    code = """
import sys
import app.schema_migrations.cli
for name in ('app.core.config', 'app.core.db', 'psycopg', 'dotenv'):
    assert name not in sys.modules, name
"""
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://forbidden:secret@host/production"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )
    assert result.returncode == 0, result.stderr
