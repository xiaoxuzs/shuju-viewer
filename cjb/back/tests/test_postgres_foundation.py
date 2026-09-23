from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Connection, Engine, URL, make_url

from postgres_support import create_schema_engine, temporary_postgres_schema


pytestmark = pytest.mark.postgres


def test_server_is_postgresql_16_and_not_forbidden(
    postgres_connection: Connection,
    postgres_database_url: URL,
) -> None:
    database_name, current_user, session_user, version_number = postgres_connection.execute(
        text(
            """
            SELECT current_database(), current_user, session_user,
                   current_setting('server_version_num')::integer
            """
        )
    ).one()
    expected_url = make_url(postgres_database_url)

    assert int(version_number) // 10000 == 16
    assert database_name == expected_url.database
    assert current_user == expected_url.username
    assert session_user == expected_url.username
    assert str(database_name).casefold() not in {
        "universal_viewer",
        "postgres",
        "template0",
        "template1",
    }


def test_skip_locked_allows_only_one_connection_to_claim_single_row(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(text("CREATE TABLE claim_probe (id bigint PRIMARY KEY, state text NOT NULL)"))
        connection.execute(text("INSERT INTO claim_probe (id, state) VALUES (1, 'QUEUED')"))

    with postgres_engine.connect() as first, postgres_engine.connect() as second:
        first_transaction = first.begin()
        second_transaction = second.begin()
        try:
            first_claim = first.execute(
                text("SELECT id FROM claim_probe WHERE state = 'QUEUED' FOR UPDATE SKIP LOCKED LIMIT 1")
            ).scalar_one_or_none()
            second_claim = second.execute(
                text("SELECT id FROM claim_probe WHERE state = 'QUEUED' FOR UPDATE SKIP LOCKED LIMIT 1")
            ).scalar_one_or_none()

            assert first_claim == 1
            assert second_claim is None
        finally:
            second_transaction.rollback()
            first_transaction.rollback()


def test_jsonb_write_merge_and_query(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(text("CREATE TABLE jsonb_probe (id integer PRIMARY KEY, payload jsonb NOT NULL)"))
        connection.execute(
            text("INSERT INTO jsonb_probe (id, payload) VALUES (1, CAST(:payload AS jsonb))"),
            {"payload": '{"stage":"READY","attempt":1}'},
        )
        connection.execute(
            text("UPDATE jsonb_probe SET payload = payload || CAST(:patch AS jsonb) WHERE id = 1"),
            {"patch": '{"attempt":2,"worker":"worker-a"}'},
        )
        row = connection.execute(
            text("SELECT payload->>'stage', (payload->>'attempt')::integer, payload->>'worker' FROM jsonb_probe")
        ).one()

    assert row == ("READY", 2, "worker-a")


def _create_partial_unique_probe(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE slug_probe (id bigserial PRIMARY KEY, slug text NOT NULL, state text NOT NULL)")
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_slug_probe_active
                ON slug_probe (slug)
                WHERE state NOT IN ('COMPLETED', 'FAILED_FINAL', 'CANCELLED', 'EXPIRED')
                """
            )
        )


def test_partial_unique_index_rejects_two_active_rows(postgres_engine: Engine) -> None:
    _create_partial_unique_probe(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(text("INSERT INTO slug_probe (slug, state) VALUES ('same-slug', 'QUEUED')"))

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as connection:
            connection.execute(text("INSERT INTO slug_probe (slug, state) VALUES ('same-slug', 'RUNNING')"))


def test_partial_unique_index_allows_terminal_rows(postgres_engine: Engine) -> None:
    _create_partial_unique_probe(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO slug_probe (slug, state)
                VALUES ('same-slug', 'COMPLETED'), ('same-slug', 'FAILED_FINAL'), ('same-slug', 'CANCELLED')
                """
            )
        )
        count = connection.execute(text("SELECT count(*) FROM slug_probe WHERE slug = 'same-slug'" )).scalar_one()

    assert count == 3


def test_postgresql_ddl_rolls_back_with_transaction(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("CREATE TABLE transactional_ddl_probe (id integer PRIMARY KEY)"))
        assert connection.execute(text("SELECT to_regclass('transactional_ddl_probe')")).scalar_one() is not None
        transaction.rollback()

        assert connection.execute(text("SELECT to_regclass('transactional_ddl_probe')")).scalar_one() is None


def test_random_schemas_are_isolated(postgres_database_url: URL) -> None:
    with temporary_postgres_schema(postgres_database_url) as first_schema:
        with temporary_postgres_schema(postgres_database_url) as second_schema:
            first_engine = create_schema_engine(postgres_database_url, first_schema)
            second_engine = create_schema_engine(postgres_database_url, second_schema)
            try:
                with first_engine.begin() as connection:
                    connection.execute(text("CREATE TABLE schema_isolation_probe (id integer PRIMARY KEY)"))
                with second_engine.connect() as connection:
                    assert connection.execute(text("SELECT to_regclass('schema_isolation_probe')")).scalar_one() is None
            finally:
                second_engine.dispose()
                first_engine.dispose()


def test_temporary_schema_is_removed(postgres_database_url: URL) -> None:
    with temporary_postgres_schema(postgres_database_url) as schema_name:
        assert schema_name.startswith("test_")

    with temporary_postgres_schema(postgres_database_url) as current_schema:
        engine = create_schema_engine(postgres_database_url, current_schema)
        try:
            with engine.connect() as connection:
                removed = connection.execute(
                    text("SELECT to_regnamespace(:schema_name)"),
                    {"schema_name": schema_name},
                ).scalar_one()
        finally:
            engine.dispose()

    assert removed is None
