from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from postgres_support import (
    PRODUCTION_IDENTITY_ENV,
    TEST_POSTGRES_URL_ENV,
    PostgresSafetyError,
    external_postgres_url_from_environment,
    redact_postgres_url,
    validate_external_postgres_url,
)


BACK_DIRECTORY = Path(__file__).resolve().parents[1]
FOUNDATION_TEST = BACK_DIRECTORY / "tests" / "test_postgres_foundation.py"
SQLITE_TEST = (
    BACK_DIRECTORY
    / "tests"
    / "test_database_engine_factory.py"
)
SQLITE_TEST_NODE = f"{SQLITE_TEST}::test_sqlite_engine_omits_queue_pool_size_options"
SAFE_TEST_URL = "postgresql+psycopg://viewer_test_user:secret@test-db:5432/viewer_test_isolated"
PRODUCTION_IDENTITY = "production-db:5432/Universal_Viewer"
SENSITIVE_PASSWORD = "viewer-test-password-must-not-leak"


def _subprocess_environment(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop(TEST_POSTGRES_URL_ENV, None)
    env.pop(PRODUCTION_IDENTITY_ENV, None)
    env["DATABASE_URL"] = (
        "postgresql+psycopg://viewer:production@forbidden-production.invalid:5432/Universal_Viewer"
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    env["PYTHONUTF8"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _run_pytest(
    tmp_path: Path,
    target: str | Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        str(target),
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(tmp_path / "pytest"),
        "-q",
        "-rs",
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=BACK_DIRECTORY,
        env=env or _subprocess_environment(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_missing_external_url_never_falls_back_to_database_url() -> None:
    env = {
        "DATABASE_URL": "postgresql+psycopg://viewer:secret@localhost:5432/Universal_Viewer",
        PRODUCTION_IDENTITY_ENV: PRODUCTION_IDENTITY,
    }

    assert external_postgres_url_from_environment(env) is None


@pytest.mark.parametrize(
    "database_name",
    ["Universal_Viewer", "universal_viewer", "postgres", "template0", "template1"],
)
def test_external_url_rejects_forbidden_database_names(database_name: str) -> None:
    url = f"postgresql+psycopg://viewer_test_user:secret@test-db:5432/{database_name}"

    with pytest.raises(PostgresSafetyError):
        validate_external_postgres_url(url, production_identity=PRODUCTION_IDENTITY)


@pytest.mark.parametrize("username", ["postgres", "viewer", "VIEWER"])
def test_external_url_rejects_production_users(username: str) -> None:
    url = f"postgresql+psycopg://{username}:secret@test-db:5432/viewer_test_isolated"

    with pytest.raises(PostgresSafetyError, match="dedicated non-production user"):
        validate_external_postgres_url(url, production_identity=PRODUCTION_IDENTITY)


@pytest.mark.parametrize(
    "database_name",
    ["viewer", "other_viewer_test", "Viewer_test_isolated", "viewer-test-isolated"],
)
def test_external_url_requires_strict_test_database_prefix(database_name: str) -> None:
    url = f"postgresql+psycopg://viewer_test_user:secret@test-db:5432/{database_name}"

    with pytest.raises(PostgresSafetyError, match="viewer_test_"):
        validate_external_postgres_url(url, production_identity=PRODUCTION_IDENTITY)


def test_external_url_rejects_non_postgresql_dialect() -> None:
    with pytest.raises(PostgresSafetyError, match="PostgreSQL"):
        validate_external_postgres_url(
            "sqlite+pysqlite:///viewer_test_isolated.sqlite",
            production_identity=PRODUCTION_IDENTITY,
        )


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("postgresql+psycopg://viewer_test_user:secret@:5432/viewer_test_isolated", "host"),
        ("postgresql+psycopg://:secret@test-db:5432/viewer_test_isolated", "user"),
        ("postgresql+psycopg://viewer_test_user:secret@test-db/viewer_test_isolated", "port"),
        ("postgresql+psycopg://viewer_test_user:secret@test-db:5432", "database name"),
    ],
)
def test_external_url_requires_explicit_target_components(url: str, message: str) -> None:
    with pytest.raises(PostgresSafetyError, match=message):
        validate_external_postgres_url(url, production_identity=PRODUCTION_IDENTITY)


@pytest.mark.parametrize(
    "query",
    [
        "options=-csearch_path%3Dpublic",
        "search_path=public",
        "role=viewer",
        "session_authorization=viewer",
        "service=production",
    ],
)
def test_external_url_rejects_session_mutating_query_parameters(query: str) -> None:
    with pytest.raises(PostgresSafetyError, match="query parameter"):
        validate_external_postgres_url(
            f"{SAFE_TEST_URL}?{query}",
            production_identity=PRODUCTION_IDENTITY,
        )


def test_external_url_preserves_safe_ssl_connection_parameter() -> None:
    normalized = validate_external_postgres_url(
        f"{SAFE_TEST_URL}?sslmode=require",
        production_identity=PRODUCTION_IDENTITY,
    )

    assert make_url(normalized).query["sslmode"] == "require"


def test_external_url_requires_production_identity() -> None:
    with pytest.raises(PostgresSafetyError, match=PRODUCTION_IDENTITY_ENV):
        validate_external_postgres_url(SAFE_TEST_URL, production_identity=None)


def test_production_identity_must_not_contain_credentials() -> None:
    with pytest.raises(PostgresSafetyError, match="must not contain database credentials"):
        validate_external_postgres_url(
            SAFE_TEST_URL,
            production_identity="postgresql://prod:secret@production-db:5432/Universal_Viewer",
        )


def test_external_url_rejects_declared_production_target() -> None:
    with pytest.raises(PostgresSafetyError, match="matches the declared production target"):
        validate_external_postgres_url(
            SAFE_TEST_URL,
            production_identity="test-db:5432/viewer_test_isolated",
        )


def test_safe_external_url_is_normalized_to_psycopg() -> None:
    normalized = validate_external_postgres_url(
        SAFE_TEST_URL.replace("postgresql+psycopg", "postgresql"),
        production_identity=PRODUCTION_IDENTITY,
    )
    parsed = make_url(normalized)

    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.database == "viewer_test_isolated"
    assert parsed.username == "viewer_test_user"


def test_password_is_redacted_from_errors_repr_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    unsafe_url = (
        f"postgresql+psycopg://viewer:{SENSITIVE_PASSWORD}@test-db:5432/viewer_test_isolated"
    )
    with pytest.raises(PostgresSafetyError) as error:
        validate_external_postgres_url(unsafe_url, production_identity=PRODUCTION_IDENTITY)

    rendered = "\n".join(
        [
            str(error.value),
            repr(make_url(unsafe_url)),
            str(make_url(unsafe_url)),
            redact_postgres_url(unsafe_url),
            caplog.text,
        ]
    )
    if SENSITIVE_PASSWORD in rendered:
        pytest.fail("A PostgreSQL password appeared in an exception, URL representation, or log", pytrace=False)
    assert ":***@" in redact_postgres_url(unsafe_url)


def test_invalid_environment_url_is_a_hard_error() -> None:
    env = {
        TEST_POSTGRES_URL_ENV: "postgresql+psycopg://viewer:secret@localhost:5432/Universal_Viewer",
        PRODUCTION_IDENTITY_ENV: PRODUCTION_IDENTITY,
    }

    with pytest.raises(PostgresSafetyError):
        external_postgres_url_from_environment(env)


def test_postgres_selection_skips_when_dedicated_url_is_missing(tmp_path: Path) -> None:
    result = _run_pytest(tmp_path, FOUNDATION_TEST, "-m", "postgres")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "8 skipped" in output
    assert "VIEWER_TEST_POSTGRES_URL未配置" in output


def test_require_postgres_fails_when_selected_url_is_missing(tmp_path: Path) -> None:
    result = _run_pytest(tmp_path, FOUNDATION_TEST, "-m", "postgres", "--require-postgres")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "VIEWER_TEST_POSTGRES_URL未配置" in output


def test_require_postgres_does_not_affect_sqlite_only_selection(tmp_path: Path) -> None:
    result = _run_pytest(
        tmp_path,
        SQLITE_TEST_NODE,
        "-m",
        "not postgres",
        "--require-postgres",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "1 passed" in output


def test_pytest_failure_output_does_not_expose_password(tmp_path: Path) -> None:
    env = _subprocess_environment(tmp_path)
    env[TEST_POSTGRES_URL_ENV] = (
        f"postgresql+psycopg://viewer:{SENSITIVE_PASSWORD}@test-db.invalid:5432/viewer_test_isolated"
    )
    env[PRODUCTION_IDENTITY_ENV] = "production-db.invalid:5432/Universal_Viewer"

    result = _run_pytest(
        tmp_path,
        FOUNDATION_TEST,
        "-m",
        "postgres",
        "--require-postgres",
        env=env,
    )
    output = result.stdout + result.stderr
    if SENSITIVE_PASSWORD in output:
        pytest.fail("A PostgreSQL password appeared in pytest stdout or stderr", pytrace=False)
    assert result.returncode != 0
    assert "dedicated non-production user" in output


def test_postgres_collect_only_creates_no_engine_or_connection(tmp_path: Path) -> None:
    spy_directory = tmp_path / "collect-spy"
    spy_directory.mkdir()
    (spy_directory / "sitecustomize.py").write_text(
        """
import socket
import psycopg
import sqlalchemy
import sqlalchemy.engine

def forbidden(*args, **kwargs):
    raise RuntimeError("collect-only attempted to create an Engine or database connection")

socket.socket.connect = forbidden
psycopg.connect = forbidden
sqlalchemy.create_engine = forbidden
sqlalchemy.engine.create_engine = forbidden
""".strip(),
        encoding="utf-8",
    )

    env = _subprocess_environment(tmp_path)
    env[TEST_POSTGRES_URL_ENV] = (
        f"postgresql+psycopg://viewer_test_user:{SENSITIVE_PASSWORD}"
        "@collect-only.invalid:5432/viewer_test_collect_only"
    )
    env[PRODUCTION_IDENTITY_ENV] = "production-db.invalid:5432/Universal_Viewer"
    env["DATABASE_URL"] = (
        "postgresql+psycopg://viewer:production@forbidden-production.invalid:5432/Universal_Viewer"
    )
    existing_python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(part for part in [str(spy_directory), existing_python_path] if part)

    result = _run_pytest(
        tmp_path,
        FOUNDATION_TEST,
        "-m",
        "postgres",
        "--collect-only",
        env=env,
    )
    output = result.stdout + result.stderr
    if SENSITIVE_PASSWORD in output:
        pytest.fail("A PostgreSQL password appeared in collect-only stdout or stderr", pytrace=False)
    assert result.returncode == 0, output
    assert "8 tests collected" in output


def test_test_support_contains_no_container_runtime_or_dependency() -> None:
    paths = [
        BACK_DIRECTORY / "pyproject.toml",
        BACK_DIRECTORY / "tests" / "conftest.py",
        BACK_DIRECTORY / "tests" / "postgres_support.py",
    ]
    contents = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
    prohibited_terms = (
        "test" + "containers",
        "postgres" + "container",
        "running_postgres_" + "container",
        "docker",
    )

    for term in prohibited_terms:
        assert term.casefold() not in contents
