from __future__ import annotations

import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from app.schema_migrations import cli
from app.schema_migrations.errors import (
    ConnectionTargetError,
    MigrationLockTimeout,
    MigrationTransactionError,
    SchemaStateError,
)
from app.schema_migrations.models import DatabaseClassification, DatabaseState, Migration


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_URL = "postgresql://operator:secret@db.example:6432/viewer_test_schema"


def _migration() -> Migration:
    return Migration(
        version=1,
        name="schema_migrations",
        path=Path("0001_schema_migrations.sql"),
        checksum="a" * 64,
        migration_type="transactional",
        sql="-- viewer-migration: transactional\nSELECT 1;\n",
    )


def _state(
    classification: DatabaseClassification,
    *,
    current: int = 0,
    pending: tuple[Migration, ...] = (),
    differences: tuple[str, ...] = (),
) -> DatabaseState:
    return DatabaseState(
        classification=classification,
        current_version=current,
        code_version=1,
        database_server_version_num=160014,
        pending=pending,
        differences=differences,
        summary="test summary",
    )


def _run(argv: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    result = cli.main(argv, env={} if env is None else env, stdout=stdout, stderr=stderr)
    return result, stdout.getvalue(), stderr.getvalue()


def test_no_command_prints_help_and_returns_two_without_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "upgrade_database", lambda *_args, **_kwargs: pytest.fail("upgrade called"))
    code, output, errors = _run([])
    assert code == 2
    assert output == ""
    assert "usage:" in errors


def test_module_process_without_command_exits_two() -> None:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "app.schema_migrations"],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_normal_database_url_is_ignored() -> None:
    code, _output, errors = _run(["status"], env={"DATABASE_URL": TEST_URL})
    assert code == 2
    assert "VIEWER_SCHEMA_DATABASE_URL" in errors


def test_dedicated_database_url_is_used_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "inspect_database", lambda _target, _config: _state(DatabaseClassification.EMPTY))
    code, output, errors = _run(["status"], env={"VIEWER_SCHEMA_DATABASE_URL": TEST_URL})
    assert code == 0
    assert "target=postgresql://operator:***@db.example:6432/viewer_test_schema" in output
    assert "secret" not in output + errors


@pytest.mark.parametrize("classification", list(DatabaseClassification))
def test_status_returns_zero_and_prints_exact_classification(
    monkeypatch: pytest.MonkeyPatch,
    classification: DatabaseClassification,
) -> None:
    monkeypatch.setattr(cli, "inspect_database", lambda _target, _config: _state(classification))
    code, output, errors = _run(["status", "--database-url", TEST_URL])
    assert code == 0
    assert f"classification={classification.value}" in output
    assert errors == ""


def test_check_passes_only_strict_current_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "check_database",
        lambda _target, _config: _state(DatabaseClassification.VERSIONED, current=1),
    )
    code, output, errors = _run(["check", "--database-url", TEST_URL])
    assert code == 0
    assert "check=PASS" in output
    assert errors == ""


def test_check_and_plan_return_four_for_nonacceptable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "check_database",
        lambda _target, _config: (_ for _ in ()).throw(SchemaStateError("strict check failed")),
    )
    code, _output, errors = _run(["check", "--database-url", TEST_URL])
    assert code == 4
    assert "strict check failed" in errors

    monkeypatch.setattr(
        cli,
        "plan_database",
        lambda _target, _config: (_ for _ in ()).throw(SchemaStateError("plan refused")),
    )
    code, _output, errors = _run(["plan", "--database-url", TEST_URL])
    assert code == 4
    assert "plan refused" in errors


def test_plan_legacy_match_lists_only_0001_and_uses_no_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "plan_database",
        lambda _target, _config: _state(
            DatabaseClassification.UNVERSIONED_LEGACY_MATCH,
            pending=(_migration(),),
        ),
    )
    monkeypatch.setattr(cli, "upgrade_database", lambda *_args, **_kwargs: pytest.fail("upgrade called"))
    code, output, errors = _run(["plan", "--database-url", TEST_URL])
    assert code == 0
    assert [line for line in output.splitlines() if line.startswith("pending=")] == [
        "pending=0001_schema_migrations"
    ]
    assert errors == ""


def test_upgrade_requires_explicit_applied_by_before_calling_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "upgrade_database", lambda *_args, **_kwargs: pytest.fail("upgrade called"))
    code, _output, errors = _run(["upgrade", "--database-url", TEST_URL])
    assert code == 2
    assert "VIEWER_SCHEMA_APPLIED_BY" in errors


def test_upgrade_accepts_dedicated_applied_by_and_reports_final_check(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_upgrade(_target: object, *, applied_by: str, config: object) -> tuple[DatabaseState, None]:
        del config
        captured["applied_by"] = applied_by
        return _state(DatabaseClassification.VERSIONED, current=1), None

    monkeypatch.setattr(cli, "upgrade_database", fake_upgrade)
    code, output, errors = _run(
        ["upgrade", "--database-url", TEST_URL],
        env={"VIEWER_SCHEMA_APPLIED_BY": "release-operator"},
    )
    assert code == 0
    assert captured == {"applied_by": "release-operator"}
    assert "check=PASS" in output
    assert "upgrade=complete" in output
    assert errors == ""


@pytest.mark.parametrize(
    ("exception", "exit_code"),
    [
        (ConnectionTargetError("connection failed"), 3),
        (SchemaStateError("schema mismatch"), 4),
        (MigrationLockTimeout("lock timeout"), 5),
        (MigrationTransactionError("migration failed"), 6),
    ],
)
def test_cli_uses_unified_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    exit_code: int,
) -> None:
    def fail(_target: object, _config: object) -> DatabaseState:
        raise exception

    monkeypatch.setattr(cli, "inspect_database", fail)
    code, _output, errors = _run(["status", "--database-url", TEST_URL])
    assert code == exit_code
    assert "error=" in errors
