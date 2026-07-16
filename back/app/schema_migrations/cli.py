from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from .errors import ExitCode, SchemaMigrationError
from .models import DatabaseState
from .runner import (
    RunnerConfig,
    check_database,
    inspect_database,
    plan_database,
    resolve_applied_by,
    resolve_database_url,
    upgrade_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.schema_migrations",
        description="Viewer PostgreSQL schema migration control",
    )
    subparsers = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("status", "show the explicit database schema classification"),
        ("check", "require a valid, current versioned schema"),
        ("plan", "show pending migrations without taking a write lock"),
        ("upgrade", "apply pending migrations under the PostgreSQL advisory lock"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--database-url", help="PostgreSQL URL; overrides VIEWER_SCHEMA_DATABASE_URL")
        if name == "upgrade":
            command.add_argument("--applied-by", help="operator identity; overrides VIEWER_SCHEMA_APPLIED_BY")
    return parser


def _write_state(output: TextIO, state: DatabaseState) -> None:
    print(f"classification={state.classification.value}", file=output)
    print(f"database_version={state.current_version:04d}", file=output)
    print(f"code_version={state.code_version:04d}", file=output)
    print(f"database_server_version_num={state.database_server_version_num}", file=output)
    print(f"summary={state.summary}", file=output)
    for difference in state.differences:
        print(f"difference={difference}", file=output)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    config: RunnerConfig | None = None,
) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = build_parser()
    if not args_list:
        parser.print_help(errors)
        return int(ExitCode.CONFIGURATION)
    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        return int(exc.code)
    if args.command is None:
        parser.print_help(errors)
        return int(ExitCode.CONFIGURATION)

    source = os.environ if env is None else env
    runner_config = RunnerConfig() if config is None else config
    try:
        target = resolve_database_url(args.database_url, source)
        print(f"target={target.redacted}", file=output)
        if args.command == "status":
            state = inspect_database(target, runner_config)
            _write_state(output, state)
            return int(ExitCode.SUCCESS)
        if args.command == "check":
            state = check_database(target, runner_config)
            _write_state(output, state)
            print("check=PASS", file=output)
            return int(ExitCode.SUCCESS)
        if args.command == "plan":
            state = plan_database(target, runner_config)
            _write_state(output, state)
            if state.pending:
                for migration in state.pending:
                    print(f"pending={migration.identifier}", file=output)
            else:
                print("pending=none", file=output)
            return int(ExitCode.SUCCESS)

        applied_by = resolve_applied_by(args.applied_by, source)
        state, git_hint = upgrade_database(target, applied_by=applied_by, config=runner_config)
        if git_hint:
            print(f"notice={git_hint}", file=errors)
        _write_state(output, state)
        print("check=PASS", file=output)
        print("upgrade=complete", file=output)
        return int(ExitCode.SUCCESS)
    except SchemaMigrationError as exc:
        print(f"error={exc}", file=errors)
        return int(exc.exit_code)
    except Exception as exc:
        print(f"error=unexpected migration failure ({type(exc).__name__})", file=errors)
        return int(ExitCode.CONNECTION)
