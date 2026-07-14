from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from sqlalchemy.engine import Engine, URL, make_url


TEST_POSTGRES_URL_ENV = "VIEWER_TEST_POSTGRES_URL"
PRODUCTION_IDENTITY_ENV = "VIEWER_PRODUCTION_DATABASE_IDENTITY"
FORBIDDEN_DATABASE_NAMES = frozenset({"universal_viewer", "postgres", "template0", "template1"})
FORBIDDEN_USER_NAMES = frozenset({"postgres", "viewer"})
_TEST_DATABASE_PATTERN = re.compile(r"viewer_test_[a-z0-9_]+\Z")
_TEST_SCHEMA_PATTERN = re.compile(r"test_[0-9a-f]{32}\Z")
_ALLOWED_CONNECTION_QUERY_KEYS = frozenset(
    {
        "application_name",
        "channel_binding",
        "connect_timeout",
        "gssencmode",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "sslcert",
        "sslcrl",
        "sslkey",
        "sslmode",
        "sslrootcert",
        "target_session_attrs",
        "tcp_user_timeout",
    }
)


class PostgresSafetyError(RuntimeError):
    """Raised when a PostgreSQL test target cannot be proven safe."""


def _make_url_without_raising(database_url: str) -> URL | None:
    try:
        return make_url(database_url)
    except Exception:
        return None


def redact_postgres_url(database_url: str | URL) -> str:
    """Render a database target without credentials or query-string values."""
    try:
        url = make_url(database_url)
    except Exception:
        return "<invalid PostgreSQL URL>"
    return url.set(query={}).render_as_string(hide_password=True)


def _database_target_identity(url: URL) -> str:
    host = (url.host or "").strip().casefold()
    database_name = (url.database or "").strip().casefold()
    if not host or url.port is None or not database_name:
        raise PostgresSafetyError("PostgreSQL target identity requires explicit host, port, and database name")
    return f"{host}:{url.port}/{database_name}"


def _production_target_identity(value: str | None) -> str:
    if not value or not value.strip():
        raise PostgresSafetyError(
            f"Explicit PostgreSQL tests require {PRODUCTION_IDENTITY_ENV} for target comparison"
        )

    identity = value.strip()
    if "://" not in identity:
        identity = f"postgresql://{identity}"
    url = _make_url_without_raising(identity)
    identity = "<redacted production identity>"
    value = "<redacted production identity>"
    if url is None:
        raise PostgresSafetyError(
            f"{PRODUCTION_IDENTITY_ENV} must be a PostgreSQL target identity without credentials"
        ) from None
    if url.username is not None or url.password is not None:
        raise PostgresSafetyError(f"{PRODUCTION_IDENTITY_ENV} must not contain database credentials")
    if url.get_backend_name() != "postgresql" or url.query:
        raise PostgresSafetyError(f"{PRODUCTION_IDENTITY_ENV} must identify one PostgreSQL target")
    return _database_target_identity(url)


def _validate_connection_query(url: URL) -> None:
    for key, value in url.query.items():
        normalized_key = key.casefold()
        if normalized_key not in _ALLOWED_CONNECTION_QUERY_KEYS:
            raise PostgresSafetyError(
                f"{TEST_POSTGRES_URL_ENV} query parameter is not permitted: {key}"
            )
        if isinstance(value, tuple):
            raise PostgresSafetyError(
                f"{TEST_POSTGRES_URL_ENV} query parameter may only be specified once: {key}"
            )


def validate_external_postgres_url(database_url: str, *, production_identity: str | None) -> str:
    """Validate an explicitly supplied native PostgreSQL test URL without connecting."""
    url = _make_url_without_raising(database_url)
    database_url = redact_postgres_url(database_url)
    if url is None:
        raise PostgresSafetyError(f"{TEST_POSTGRES_URL_ENV} is not a valid database URL") from None

    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise PostgresSafetyError(f"{TEST_POSTGRES_URL_ENV} must use PostgreSQL with psycopg")

    database_name = (url.database or "").strip()
    if database_name.casefold() in FORBIDDEN_DATABASE_NAMES:
        raise PostgresSafetyError("Refusing a forbidden PostgreSQL database name")
    if not _TEST_DATABASE_PATTERN.fullmatch(database_name):
        raise PostgresSafetyError("PostgreSQL test database name must match viewer_test_[a-z0-9_]+")

    username = (url.username or "").strip()
    if not username:
        raise PostgresSafetyError(f"{TEST_POSTGRES_URL_ENV} requires an explicit user")
    if username.casefold() in FORBIDDEN_USER_NAMES:
        raise PostgresSafetyError("PostgreSQL tests require a dedicated non-production user")
    if not url.host:
        raise PostgresSafetyError(f"{TEST_POSTGRES_URL_ENV} requires an explicit host")
    if url.port is None:
        raise PostgresSafetyError(f"{TEST_POSTGRES_URL_ENV} requires an explicit port")

    _validate_connection_query(url)
    test_identity = _database_target_identity(url)
    if test_identity == _production_target_identity(production_identity):
        raise PostgresSafetyError("PostgreSQL test target matches the declared production target")

    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def external_postgres_url_from_environment(env: Mapping[str, str] | None = None) -> str | None:
    """Read only dedicated test-target variables; never inspect DATABASE_URL or dotenv."""
    source = os.environ if env is None else env
    value = source.get(TEST_POSTGRES_URL_ENV, "").strip()
    if not value:
        return None
    production_identity = source.get(PRODUCTION_IDENTITY_ENV)
    source = {}
    try:
        return validate_external_postgres_url(value, production_identity=production_identity)
    finally:
        value = "<redacted PostgreSQL URL>"
        production_identity = "<redacted production identity>"


def _connect(database_url: str | URL):
    import psycopg

    url = make_url(database_url)
    _validate_connection_query(url)
    query_options = {key: value for key, value in url.query.items()}
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        **query_options,
    )


def verify_postgres_runtime(database_url: str | URL, *, expected_major: int) -> None:
    """Verify server and role identity before any test schema or table is created."""
    url = make_url(database_url)
    expected_database = url.database or ""
    expected_user = url.username or ""
    with _connect(database_url) as connection:
        database_name, current_user, session_user, version_number = connection.execute(
            """
            SELECT current_database(), current_user, session_user,
                   current_setting('server_version_num')::integer
            """
        ).fetchone()
        if str(database_name) != expected_database:
            raise PostgresSafetyError("Connected PostgreSQL database does not match the validated URL")
        if str(current_user) != expected_user or str(session_user) != expected_user:
            raise PostgresSafetyError("Connected PostgreSQL role identity does not match the validated URL")
        if int(version_number) // 10000 != expected_major:
            raise PostgresSafetyError(f"PostgreSQL major version {expected_major} is required")

        role = connection.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        if role is None or any(bool(value) for value in role):
            raise PostgresSafetyError("Connected PostgreSQL user is not a restricted test role")


@contextmanager
def temporary_postgres_schema(database_url: str | URL) -> Iterator[str]:
    """Create and remove one strictly named schema on an already validated test database."""
    from psycopg import sql

    schema_name = f"test_{uuid.uuid4().hex}"
    if not _TEST_SCHEMA_PATTERN.fullmatch(schema_name):
        raise AssertionError("Generated PostgreSQL test schema name is invalid")

    with _connect(database_url) as connection:
        connection.autocommit = True
        statement = sql.SQL("CREATE SCHEMA {} AUTHORIZATION CURRENT_USER").format(sql.Identifier(schema_name))
        connection.execute(statement)

    try:
        yield schema_name
    finally:
        if not _TEST_SCHEMA_PATTERN.fullmatch(schema_name):
            raise RuntimeError(f"Refusing to remove unsafe PostgreSQL test schema {schema_name}")
        try:
            with _connect(database_url) as connection:
                connection.autocommit = True
                statement = sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
                connection.execute(statement)
        except Exception:
            raise RuntimeError(f"Failed to remove PostgreSQL test schema {schema_name}") from None


def create_schema_engine(database_url: str | URL, schema_name: str) -> Engine:
    if not _TEST_SCHEMA_PATTERN.fullmatch(schema_name):
        raise PostgresSafetyError("Refusing to create an Engine for an unsafe test schema name")

    from psycopg import sql
    from sqlalchemy import event

    from app.core.db import create_database_engine

    engine = create_database_engine(database_url, pool_size=5, max_overflow=0)

    @event.listens_for(engine, "connect")
    def set_test_schema_search_path(dbapi_connection, _connection_record) -> None:
        previous_autocommit = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            with dbapi_connection.cursor() as cursor:
                statement = sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema_name))
                cursor.execute(statement)
        finally:
            dbapi_connection.autocommit = previous_autocommit

    return engine
