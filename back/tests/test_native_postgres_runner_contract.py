from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


BACK_ROOT = Path(__file__).resolve().parents[1]
RUNNER = BACK_ROOT / "scripts" / "run_native_postgres_tests.sh"


@pytest.fixture(scope="module")
def runner_text() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_runner_exists_with_strict_shell_mode_and_fixed_lock(runner_text: str) -> None:
    assert runner_text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in runner_text
    assert 'LOCK_FILE="/run/lock/viewer-native-pg16-test.lock"' in runner_text
    assert 'exec 9>"$LOCK_FILE"' in runner_text
    assert "flock -n 9" in runner_text
    assert '[[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]]' in runner_text
    assert '[[ "$(stat -c \'%u\' /run/lock)" == "0" ]]' in runner_text
    assert "${BASH_SOURCE[0]}" not in next(
        line for line in runner_text.splitlines() if "flock -n" in line
    )


def test_runner_requires_root_and_wraps_postgres_tools_with_runuser(runner_text: str) -> None:
    assert "((EUID == 0))" in runner_text
    assert "runuser -u postgres --" in runner_text
    assert re.search(r"pg_run\(\) \{\s+runuser -u postgres -- \"\$@\"", runner_text)

    for variable in (
        "PG_INITDB",
        "PG_CTL",
        "PG_ISREADY",
        "PG_CREATEUSER",
        "PG_CREATEDB",
        "PG_PSQL",
    ):
        invocation_lines = [line.strip() for line in runner_text.splitlines() if f'"${variable}"' in line]
        assert invocation_lines
        assert all("pg_run " in line or "=" in line for line in invocation_lines)


def test_runner_has_no_container_or_broad_process_stop_path(runner_text: str) -> None:
    lowered = runner_text.casefold()
    assert "docker" not in lowered
    assert "testcontainers" not in lowered
    assert "pkill" not in lowered
    assert "killall" not in lowered
    assert "service postgresql stop" not in lowered
    assert "pg_ctlcluster" not in lowered


def test_runner_does_not_modify_or_connect_to_production_cluster(runner_text: str) -> None:
    assert "/var/lib/postgresql/16/main" not in runner_text
    assert "back/.env" not in runner_text
    assert "postgresql.conf" in runner_text
    assert "pg_hba.conf" in runner_text

    production_ready_function = re.search(
        r"production_postgres_ready\(\) \{(?P<body>.*?)\n\}",
        runner_text,
        flags=re.DOTALL,
    )
    assert production_ready_function is not None
    production_ready_body = production_ready_function.group("body")
    assert 'pg_run "$PG_ISREADY"' in production_ready_body
    assert '--port "$PRODUCTION_PORT"' in production_ready_body
    assert runner_text.count('"$PRODUCTION_PORT"') == 1

    production_identity_lines = [line for line in runner_text.splitlines() if "PRODUCTION_IDENTITY" in line]
    assert production_identity_lines
    assert all(
        "readonly PRODUCTION_IDENTITY" in line
        or "VIEWER_PRODUCTION_DATABASE_IDENTITY" in line
        for line in production_identity_lines
    )


def test_runner_overwrites_hba_with_exact_local_rules(runner_text: str) -> None:
    expected_rules = (
        "local all postgres trust",
        "local all all reject",
        "local replication all reject",
        "host %s %s 127.0.0.1/32 trust",
        "host all all 127.0.0.1/32 reject",
        "host replication all 127.0.0.1/32 reject",
        "host all all 0.0.0.0/0 reject",
        "host replication all 0.0.0.0/0 reject",
        "host all all ::0/0 reject",
        "host replication all ::0/0 reject",
    )
    for rule in expected_rules:
        assert rule in runner_text
    assert '} >"$PGDATA/pg_hba.conf"' in runner_text
    assert "host all all 0.0.0.0/0 trust" not in runner_text
    assert "host all all ::0/0 trust" not in runner_text


def test_runner_creates_and_verifies_restricted_role_and_database(runner_text: str) -> None:
    for flag in (
        "--login",
        "--no-superuser",
        "--no-createdb",
        "--no-createrole",
        "--no-replication",
        "--no-bypassrls",
    ):
        assert flag in runner_text
    assert '--owner "$TEST_ROLE"' in runner_text
    assert "rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls" in runner_text
    assert '[[ "$role_check" == "t|f|f|f|f|f" ]]' in runner_text
    assert "db.datname = :'database_name'" in runner_text
    assert "pg_roles WHERE rolname = :'role_name'" in runner_text


def test_runner_uses_fresh_pgdata_for_bounded_port_retries(runner_text: str) -> None:
    assert 'readonly MAX_PORT_ATTEMPTS=10' in runner_text
    assert "validate_port" in runner_text
    assert "port != 5432 && port != 50001 && port != 50002" in runner_text
    assert '[[ ! -e "$PGDATA" && ! -e "$SOCKET_DIR" ]]' in runner_text
    assert 'mv -- "$PGDATA" "$failed_data"' in runner_text
    assert 'rm -f -- "$PGDATA/postmaster.pid"' in runner_text
    assert "temporary_postmaster_is_running && die" in runner_text
    assert "find_temporary_postmaster_pids" in runner_text
    assert "for process_dir in /proc/[0-9]*" in runner_text
    assert '[[ -z "$matching_processes" ]]' in runner_text


def test_runner_limits_immediate_stop_to_proven_temporary_postmaster(runner_text: str) -> None:
    fast_index = runner_text.index('--mode fast --wait --timeout 30 stop')
    evidence_index = runner_text.index('verify_postmaster_evidence "$pid"')
    immediate_index = runner_text.index('--mode immediate --wait --timeout 30 stop')
    assert fast_index < evidence_index < immediate_index
    assert '"/proc/$pid/cmdline"' in runner_text
    assert '"/proc/$pid/exe"' in runner_text
    assert "postmaster.pid" in runner_text
    assert 'pid_data="$(realpath -e -- "$pid_data")"' in runner_text
    assert "process exists without a usable postmaster.pid" in runner_text
    assert 'matching_processes="$(find_temporary_postmaster_pids)"' in runner_text


def test_runner_requires_explicit_production_data_root_and_complete_summary(runner_text: str) -> None:
    assert 'supplied="${VIEWER_PRODUCTION_DATA_ROOT:-}"' in runner_text
    assert '[[ ! -L "$supplied" ]]' in runner_text
    assert 'resolved="$(realpath -e -- "$supplied")"' in runner_text
    assert '[[ "$resolved" != "/" ]]' in runner_text
    assert '[[ "$TEMP_BASE" != "$resolved" && "$TEMP_BASE" != "$resolved"/* ]]' in runner_text
    assert "Unable to obtain a complete production DATA_ROOT baseline" in runner_text
    assert "set -Eeuo pipefail" in runner_text
    assert "find -P" in runner_text
    assert "-printf '%y\\t%s\\t%T@\\n'" in runner_text


def test_runner_sets_isolated_application_environment(runner_text: str) -> None:
    assert 'export VIEWER_ENV="test"' in runner_text
    assert 'export DATABASE_URL="sqlite+pysqlite:///$RUN_ROOT/viewer-test.sqlite"' in runner_text
    assert 'export DATA_ROOT="$RUN_ROOT/viewer-data"' in runner_text
    assert 'export VIEWER_TEST_POSTGRES_URL="postgresql+psycopg://' in runner_text
    assert 'export PYTHONPYCACHEPREFIX="$RUN_ROOT/pycache"' in runner_text
    assert '-p no:cacheprovider' in runner_text
    assert '--basetemp "$basetemp"' in runner_text


def test_runner_defaults_to_postgres_only_and_never_runs_deployment_commands(runner_text: str) -> None:
    assert "RUN_NON_POSTGRES=0" in runner_text
    assert "if ((RUN_NON_POSTGRES)); then" in runner_text
    assert "-m postgres --require-postgres" in runner_text
    assert '-m "not postgres"' in runner_text

    for forbidden in (
        "uv sync",
        "update.sh",
        "start-all.sh",
        "start-backend.sh",
        "git pull",
        "systemctl restart",
        "systemctl stop",
        "systemctl reload",
    ):
        assert forbidden not in runner_text


def test_runner_has_idempotent_signal_cleanup_and_strict_deletion_proof(runner_text: str) -> None:
    assert "trap 'cleanup $?' EXIT" in runner_text
    assert "trap 'cleanup 130' INT" in runner_text
    assert "trap 'cleanup 143' TERM" in runner_text
    assert "trap 'cleanup 129' HUP" in runner_text
    assert "if ((CLEANUP_STARTED)); then" in runner_text
    assert "viewer-pg16-test-[0-9a-f]{32}" in runner_text
    assert '[[ -f "$MARKER_FILE" && ! -L "$MARKER_FILE" ]]' in runner_text
    assert '[[ "$marker_owner" == "0" ]]' in runner_text
    assert '[[ "$(stat -c \'%u\' "$run_real")" == "0" ]]' in runner_text
    assert '[[ "$marker_run_id" == "$RUN_ID" ]]' in runner_text
    assert '[[ "$pgdata_real" == "$run_real/data" ]]' in runner_text
    assert 'rm -rf --one-file-system -- "$RUN_ROOT"' in runner_text


def test_runner_treats_service_pid_changes_as_failures_without_repair(runner_text: str) -> None:
    assert "Unable to record any Uvicorn PID" in runner_text
    assert "Unable to record any Nginx PID" in runner_text
    assert "Production PostgreSQL PID changed" in runner_text
    assert "Uvicorn PID set changed" in runner_text
    assert "Nginx PID set changed" in runner_text
    assert "the runner will not attempt repair" in runner_text


def test_runner_is_valid_bash_syntax_without_executing_it() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable; syntax validation requires a shell parser")
    result = subprocess.run(
        [bash, "-n", str(RUNNER)],
        cwd=BACK_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
