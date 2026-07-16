from __future__ import annotations

import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from app.schema_migrations.catalog import baseline_catalog, collect_catalog, load_legacy_baseline
from app.schema_migrations.discovery import discover_migrations
from app.schema_migrations.errors import MigrationLockTimeout, MigrationTransactionError, SchemaStateError
from app.schema_migrations.models import DatabaseClassification
from app.schema_migrations.runner import (
    RunnerConfig,
    advisory_lock_key,
    check_database,
    inspect_database,
    plan_database,
    upgrade_database,
    validate_database_url,
)
from postgres_support import (
    FORBIDDEN_DATABASE_NAMES,
    FORBIDDEN_USER_NAMES,
    TEST_POSTGRES_URL_ENV,
    verify_postgres_runtime,
)


pytestmark = pytest.mark.postgres

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
SCHEMA_SQL = REPOSITORY_ROOT / "docs" / "universal_schema.sql"
MIGRATIONS = BACKEND_ROOT / "migrations"
BASELINE = MIGRATIONS / "legacy_baseline_v1.json"


def _connect(target: object):
    import psycopg

    return psycopg.connect(target.dsn, autocommit=True)


def _reset_public(target: object) -> None:
    with _connect(target) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public AUTHORIZATION CURRENT_USER")


@pytest.fixture(scope="session")
def schema_migration_target(postgres_database_url: URL):
    if not os.environ.get(TEST_POSTGRES_URL_ENV, "").strip():
        pytest.fail(f"{TEST_POSTGRES_URL_ENV} must be the source of the migration test URL", pytrace=False)
    if os.environ.get("VIEWER_ENV") != "test":
        pytest.fail("schema migration PostgreSQL tests require VIEWER_ENV=test", pytrace=False)

    data_root_value = os.environ.get("DATA_ROOT", "")
    if not data_root_value:
        pytest.fail("schema migration PostgreSQL tests require an isolated DATA_ROOT", pytrace=False)
    data_root = Path(data_root_value).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        data_root.relative_to(temp_root)
    except ValueError:
        pytest.fail("schema migration PostgreSQL tests require DATA_ROOT inside the system temp directory", pytrace=False)
    if data_root == temp_root:
        pytest.fail("schema migration PostgreSQL tests refuse the system temp root itself", pytrace=False)

    database_name = (postgres_database_url.database or "").casefold()
    username = (postgres_database_url.username or "").casefold()
    if database_name in FORBIDDEN_DATABASE_NAMES or database_name == "universal_viewer":
        pytest.fail("schema migration PostgreSQL tests refuse Universal_Viewer and system databases", pytrace=False)
    if username in FORBIDDEN_USER_NAMES:
        pytest.fail("schema migration PostgreSQL tests require a dedicated restricted role", pytrace=False)
    if postgres_database_url.port == 5432:
        pytest.fail("schema migration PostgreSQL tests refuse the formal PostgreSQL port 5432", pytrace=False)

    raw_url = postgres_database_url.render_as_string(hide_password=False)
    verify_postgres_runtime(raw_url, expected_major=16)
    return validate_database_url(raw_url)


@pytest.fixture(autouse=True)
def reset_public_schema(schema_migration_target: object):
    _reset_public(schema_migration_target)
    try:
        yield
    finally:
        _reset_public(schema_migration_target)


def _initialize_legacy_schema(target: object) -> None:
    schema_sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with _connect(target) as connection:
        connection.execute(schema_sql, prepare=False)


def _query_one(target: object, sql: str, params: object = None) -> tuple[object, ...]:
    with _connect(target) as connection:
        return connection.execute(sql, params).fetchone()


def _query_all(target: object, sql: str, params: object = None) -> list[tuple[object, ...]]:
    with _connect(target) as connection:
        return connection.execute(sql, params).fetchall()


def _catalog(target: object) -> dict[str, object]:
    with _connect(target) as connection:
        return collect_catalog(connection)


def _upgrade(target: object, *, config: RunnerConfig = RunnerConfig()):
    return upgrade_database(target, applied_by="postgres-test-operator", config=config)


def _copy_migration(directory: Path, version: int = 1) -> Path:
    source = MIGRATIONS / f"{version:04d}_schema_migrations.sql"
    destination = directory / source.name
    shutil.copyfile(source, destination)
    return destination


def _write_future_migration(directory: Path, version: int, name: str, sql: str) -> Path:
    path = directory / f"{version:04d}_{name}.sql"
    path.write_bytes(f"-- viewer-migration: transactional\n{sql.rstrip()}\n".encode("utf-8"))
    return path


def _insert_history(target: object, *, version: int, name: str, checksum: str) -> None:
    with _connect(target) as connection:
        connection.execute(
            """
            INSERT INTO public.schema_migrations (
                version, name, checksum, applied_by, execution_ms,
                application_version, git_commit, database_server_version_num
            )
            VALUES (%s, %s, %s, 'postgres-test-operator', 0, '0.1.0', NULL,
                    current_setting('server_version_num')::integer)
            """,
            (version, name, checksum),
        )


def test_target_safety_is_proven_before_public_schema_rebuild(
    schema_migration_target: object,
) -> None:
    with _connect(schema_migration_target) as connection:
        database_name, current_user, session_user, port, version_num = connection.execute(
            """
            SELECT current_database(), current_user, session_user,
                   inet_server_port(), current_setting('server_version_num')::integer
            """
        ).fetchone()
    assert str(database_name).casefold() != "universal_viewer"
    assert int(port) != 5432
    assert current_user == session_user
    assert str(current_user).casefold() not in FORBIDDEN_USER_NAMES
    assert int(version_num) // 10000 == 16
    assert os.environ["VIEWER_ENV"] == "test"
    assert Path(os.environ["DATA_ROOT"]).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())


def test_universal_schema_catalog_exactly_matches_versioned_legacy_baseline(
    schema_migration_target: object,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    expected = baseline_catalog(load_legacy_baseline(BASELINE))

    assert _catalog(schema_migration_target) == expected
    assert inspect_database(schema_migration_target).classification is DatabaseClassification.UNVERSIONED_LEGACY_MATCH


def test_plan_lists_only_0001_and_is_catalog_read_only(schema_migration_target: object) -> None:
    _initialize_legacy_schema(schema_migration_target)
    before = _catalog(schema_migration_target)

    state = plan_database(schema_migration_target)

    after = _catalog(schema_migration_target)
    assert [migration.identifier for migration in state.pending] == ["0001_schema_migrations"]
    assert before == after
    assert _query_one(
        schema_migration_target,
        "SELECT pg_catalog.to_regclass('public.schema_migrations')",
    )[0] is None


def test_upgrade_creates_version_table_function_triggers_and_complete_record(
    schema_migration_target: object,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    final_state, _hint = _upgrade(schema_migration_target)

    assert final_state.classification is DatabaseClassification.VERSIONED
    catalog = _catalog(schema_migration_target)
    assert any(row["name"] == "schema_migrations" for row in catalog["relations"])
    assert [row["name"] for row in catalog["functions"] if row["name"] == "schema_migrations_reject_mutation"] == [
        "schema_migrations_reject_mutation"
    ]
    assert {
        row["name"] for row in catalog["triggers"] if row["relation"] == "schema_migrations"
    } == {"schema_migrations_reject_update_delete", "schema_migrations_reject_truncate"}

    row = _query_one(
        schema_migration_target,
        """
        SELECT version, name, checksum, applied_at IS NOT NULL, applied_by,
               execution_ms, application_version, git_commit,
               database_server_version_num
        FROM public.schema_migrations
        """,
    )
    migration = discover_migrations(MIGRATIONS)[0]
    assert row[0:3] == (1, "schema_migrations", migration.checksum)
    assert row[3] is True
    assert row[4] == "postgres-test-operator"
    assert int(row[5]) >= 0
    assert row[6] == "0.1.0"
    assert row[7] is None or len(str(row[7])) in {40, 64}
    assert int(row[8]) // 10000 == 16


def test_repeated_upgrade_is_zero_side_effect_and_check_passes(schema_migration_target: object) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    before_history = _query_all(schema_migration_target, "SELECT * FROM public.schema_migrations ORDER BY version")
    before_catalog = _catalog(schema_migration_target)

    final_state, _hint = _upgrade(schema_migration_target)

    assert final_state.is_strictly_current
    assert check_database(schema_migration_target).is_strictly_current
    assert _query_all(schema_migration_target, "SELECT * FROM public.schema_migrations ORDER BY version") == before_history
    assert _catalog(schema_migration_target) == before_catalog


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE public.schema_migrations SET name = name WHERE false",
        "DELETE FROM public.schema_migrations WHERE false",
        "TRUNCATE public.schema_migrations",
    ],
)
def test_append_only_triggers_reject_update_delete_and_truncate(
    schema_migration_target: object,
    statement: str,
) -> None:
    import psycopg

    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    with _connect(schema_migration_target) as connection:
        with pytest.raises(psycopg.Error) as exc_info:
            connection.execute(statement)
    assert exc_info.value.sqlstate == "55000"


@pytest.mark.parametrize(
    "mutation",
    [
        "CREATE TABLE public.unexpected_relation (id integer)",
        "ALTER TABLE public.runs DROP COLUMN run_metadata",
        "DROP INDEX public.idx_im_dataset_q; CREATE INDEX idx_im_dataset_q ON public.identification_matches (q_value, dataset_id)",
        "ALTER SEQUENCE public.datasets_dataset_id_seq OWNED BY NONE",
    ],
)
def test_legacy_catalog_drift_is_rejected_before_any_migration_ddl(
    schema_migration_target: object,
    mutation: str,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    with _connect(schema_migration_target) as connection:
        connection.execute(mutation, prepare=False)

    state = inspect_database(schema_migration_target)
    assert state.classification is DatabaseClassification.UNVERSIONED_LEGACY_MISMATCH
    with pytest.raises(SchemaStateError, match="UNVERSIONED_LEGACY_MISMATCH"):
        _upgrade(schema_migration_target)
    assert _query_one(
        schema_migration_target,
        "SELECT pg_catalog.to_regclass('public.schema_migrations')",
    )[0] is None


def test_empty_database_refuses_upgrade(schema_migration_target: object) -> None:
    assert inspect_database(schema_migration_target).classification is DatabaseClassification.EMPTY
    with pytest.raises(SchemaStateError, match="EMPTY"):
        _upgrade(schema_migration_target)
    assert _query_one(
        schema_migration_target,
        "SELECT pg_catalog.to_regclass('public.schema_migrations')",
    )[0] is None


def test_migration_sql_failure_rolls_back_ddl_and_history(
    schema_migration_target: object,
    tmp_path: Path,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    _copy_migration(tmp_path)
    _write_future_migration(
        tmp_path,
        2,
        "failing_sql",
        "CREATE TABLE public.must_rollback (id integer);\nSELECT 1 / 0;",
    )

    with pytest.raises(MigrationTransactionError, match="rolled back"):
        _upgrade(schema_migration_target, config=RunnerConfig(migration_directory=tmp_path))
    assert _query_one(schema_migration_target, "SELECT pg_catalog.to_regclass('public.must_rollback')")[0] is None
    assert _query_all(schema_migration_target, "SELECT version FROM public.schema_migrations ORDER BY version") == [(1,)]


def test_history_insert_failure_rolls_back_migration_ddl(
    schema_migration_target: object,
    tmp_path: Path,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    _copy_migration(tmp_path)
    _write_future_migration(
        tmp_path,
        2,
        "failing_record",
        """
        CREATE TABLE public.must_rollback_record (id integer);
        ALTER TABLE public.schema_migrations
            ADD CONSTRAINT reject_version_two CHECK (version <> 2);
        """,
    )

    with pytest.raises(MigrationTransactionError, match="rolled back"):
        _upgrade(schema_migration_target, config=RunnerConfig(migration_directory=tmp_path))
    assert _query_one(
        schema_migration_target,
        "SELECT pg_catalog.to_regclass('public.must_rollback_record')",
    )[0] is None
    assert _query_all(schema_migration_target, "SELECT version FROM public.schema_migrations ORDER BY version") == [(1,)]


def test_applied_checksum_drift_is_rejected(schema_migration_target: object, tmp_path: Path) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    copied = _copy_migration(tmp_path)
    copied.write_bytes(copied.read_bytes() + b"\n-- changed after application\n")

    state = inspect_database(schema_migration_target, RunnerConfig(migration_directory=tmp_path))
    assert state.classification is DatabaseClassification.VERSIONED_INVALID
    assert any("checksum differs" in item for item in state.differences)


def test_database_version_ahead_of_code_is_rejected(schema_migration_target: object) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    _insert_history(schema_migration_target, version=2, name="future", checksum="f" * 64)

    state = inspect_database(schema_migration_target)
    assert state.classification is DatabaseClassification.VERSIONED_INVALID
    assert any("higher than code" in item for item in state.differences)


def test_missing_intermediate_database_version_is_rejected(
    schema_migration_target: object,
    tmp_path: Path,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)
    _copy_migration(tmp_path)
    _write_future_migration(tmp_path, 2, "second", "SELECT 2;")
    third = _write_future_migration(tmp_path, 3, "third", "SELECT 3;")
    third_checksum = discover_migrations(tmp_path)[2].checksum
    assert third.exists()
    _insert_history(schema_migration_target, version=3, name="third", checksum=third_checksum)

    state = inspect_database(schema_migration_target, RunnerConfig(migration_directory=tmp_path))
    assert state.classification is DatabaseClassification.VERSIONED_INVALID
    assert any("not continuous" in item for item in state.differences)


def test_two_waiting_upgrades_apply_0001_once_and_second_rechecks_after_lock(
    schema_migration_target: object,
) -> None:
    _initialize_legacy_schema(schema_migration_target)
    config = RunnerConfig(advisory_lock_timeout_seconds=5, advisory_lock_poll_seconds=0.02)
    with _connect(schema_migration_target) as blocker:
        assert blocker.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s)", (advisory_lock_key(),)
        ).fetchone()[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_upgrade, schema_migration_target, config=config) for _ in range(2)]
            time.sleep(0.15)
            assert not any(future.done() for future in futures)
            blocker.execute("SELECT pg_catalog.pg_advisory_unlock(%s)", (advisory_lock_key(),))
            results = [future.result(timeout=10)[0] for future in futures]

    assert all(state.is_strictly_current for state in results)
    assert _query_all(schema_migration_target, "SELECT version FROM public.schema_migrations") == [(1,)]


def test_lock_timeout_is_explicit_and_does_not_create_objects(schema_migration_target: object) -> None:
    _initialize_legacy_schema(schema_migration_target)
    config = RunnerConfig(advisory_lock_timeout_seconds=0.1, advisory_lock_poll_seconds=0.02)
    with _connect(schema_migration_target) as blocker:
        assert blocker.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s)", (advisory_lock_key(),)
        ).fetchone()[0]
        with pytest.raises(MigrationLockTimeout, match="timed out"):
            _upgrade(schema_migration_target, config=config)
        blocker.execute("SELECT pg_catalog.pg_advisory_unlock(%s)", (advisory_lock_key(),))
    assert _query_one(
        schema_migration_target,
        "SELECT pg_catalog.to_regclass('public.schema_migrations')",
    )[0] is None


def test_failure_releases_session_advisory_lock(schema_migration_target: object) -> None:
    with pytest.raises(SchemaStateError, match="EMPTY"):
        _upgrade(schema_migration_target)
    with _connect(schema_migration_target) as connection:
        assert connection.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s)", (advisory_lock_key(),)
        ).fetchone()[0]
        connection.execute("SELECT pg_catalog.pg_advisory_unlock(%s)", (advisory_lock_key(),))


def test_public_schema_can_be_reset_after_migration_tests(schema_migration_target: object) -> None:
    _initialize_legacy_schema(schema_migration_target)
    _upgrade(schema_migration_target)

    _reset_public(schema_migration_target)

    assert inspect_database(schema_migration_target).classification is DatabaseClassification.EMPTY
