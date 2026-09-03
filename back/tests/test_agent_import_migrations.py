from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, inspect

from app.agent_import.migrations import _widen_analysis_category_column, ensure_agent_import_schema


class _ScalarResult:
    def __init__(self, value: int | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> int | None:
        return self.value


class _PostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, current_length: int | None) -> None:
        self.current_length = current_length
        self.statements: list[str] = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "information_schema.columns" in sql:
            return _ScalarResult(self.current_length)
        return _ScalarResult(None)


def test_new_analysis_category_column_accepts_the_http_contract_width() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    ensure_agent_import_schema(engine)

    column = next(
        item
        for item in inspect(engine).get_columns("agent_import_cases")
        if item["name"] == "analysis_category"
    )
    assert column["type"].length == 80


def test_existing_postgres_analysis_category_column_is_widened_once() -> None:
    connection = _PostgresConnection(current_length=24)

    _widen_analysis_category_column(connection)

    assert len(connection.statements) == 2
    assert "TYPE VARCHAR(80)" in connection.statements[1]


def test_wide_postgres_analysis_category_column_is_left_unchanged() -> None:
    connection = _PostgresConnection(current_length=80)

    _widen_analysis_category_column(connection)

    assert len(connection.statements) == 1
