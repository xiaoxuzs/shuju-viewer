from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.engine import Connection, Engine, URL, make_url

from postgres_support import (
    PostgresSafetyError,
    create_schema_engine,
    external_postgres_url_from_environment,
    temporary_postgres_schema,
    verify_postgres_runtime,
)


_TEST_ENV_KEYS = ("VIEWER_ENV", "DATABASE_URL", "DATA_ROOT")
_PREVIOUS_ENV = {name: os.environ.get(name) for name in _TEST_ENV_KEYS}
_PREVIOUS_DONT_WRITE_BYTECODE = sys.dont_write_bytecode
_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="viewer-pytest-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name).resolve()
_TEST_DATA_ROOT = _TEST_ROOT / "data"
_TEST_DATA_ROOT.mkdir()

os.environ["VIEWER_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(_TEST_ROOT / 'viewer-test.sqlite').as_posix()}"
os.environ["DATA_ROOT"] = str(_TEST_DATA_ROOT)
sys.dont_write_bytecode = True


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres",
        action="store_true",
        default=False,
        help="Fail when selected PostgreSQL tests lack a safe VIEWER_TEST_POSTGRES_URL.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    marker_expression = config.getoption("-m") or ""
    postgres_selected = bool(re.search(r"\bpostgres\b", marker_expression))
    if postgres_selected or config.getoption("--require-postgres"):
        return

    skip_postgres = pytest.mark.skip(reason="PostgreSQL tests require explicit selection with -m postgres")
    for item in items:
        if item.get_closest_marker("postgres") is not None:
            item.add_marker(skip_postgres)


@pytest.fixture(scope="session")
def postgres_database_url(request: pytest.FixtureRequest) -> URL:
    try:
        database_url = external_postgres_url_from_environment()
    except PostgresSafetyError as exc:
        pytest.fail(str(exc), pytrace=False)
    if database_url is None:
        message = "VIEWER_TEST_POSTGRES_URL未配置"
        if request.config.getoption("--require-postgres"):
            pytest.fail(message, pytrace=False)
        pytest.skip(message)

    try:
        verify_postgres_runtime(database_url, expected_major=16)
    except PostgresSafetyError as exc:
        pytest.fail(str(exc), pytrace=False)
    except Exception as exc:
        pytest.fail(
            f"PostgreSQL test preflight failed before test DDL: {type(exc).__name__}",
            pytrace=False,
        )
    safe_url = make_url(database_url)
    database_url = "<redacted PostgreSQL URL>"
    return safe_url


@pytest.fixture
def postgres_schema(postgres_database_url: URL) -> Iterator[str]:
    with temporary_postgres_schema(postgres_database_url) as schema_name:
        yield schema_name


@pytest.fixture
def postgres_engine(postgres_database_url: URL, postgres_schema: str) -> Iterator[Engine]:
    engine = create_schema_engine(postgres_database_url, postgres_schema)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def postgres_connection(postgres_engine: Engine) -> Iterator[Connection]:
    with postgres_engine.connect() as connection:
        yield connection


def pytest_unconfigure(config: object) -> None:
    del config
    db_module = sys.modules.get("app.core.db")
    if isinstance(db_module, ModuleType):
        engine = getattr(db_module, "engine", None)
        if engine is not None:
            engine.dispose()

    for name, value in _PREVIOUS_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    sys.dont_write_bytecode = _PREVIOUS_DONT_WRITE_BYTECODE
    _TEST_DIRECTORY.cleanup()
