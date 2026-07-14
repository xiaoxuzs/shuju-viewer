from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core import db


def _capture_engine_options(monkeypatch, database_url: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **options: Any) -> object:
        captured["url"] = url
        captured.update(options)
        return object()

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    db.create_database_engine(database_url)
    return captured


def test_sqlite_engine_omits_queue_pool_size_options(monkeypatch, tmp_path: Path) -> None:
    options = _capture_engine_options(
        monkeypatch,
        f"sqlite+pysqlite:///{(tmp_path / 'factory.sqlite').as_posix()}",
    )

    assert options["pool_pre_ping"] is True
    assert "pool_size" not in options
    assert "max_overflow" not in options


def test_postgresql_engine_preserves_production_pool_options(monkeypatch) -> None:
    options = _capture_engine_options(
        monkeypatch,
        "postgresql+psycopg://viewer:secret@db.example/viewer_test",
    )

    assert options["pool_pre_ping"] is True
    assert options["pool_size"] == 10
    assert options["max_overflow"] == 20


def test_file_sqlite_engine_can_connect_without_pool_argument_error(tmp_path: Path) -> None:
    database_path = tmp_path / "working.sqlite"
    engine = db.create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()
