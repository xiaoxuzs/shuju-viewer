"""Database engine, session factory and dependency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def create_database_engine(database_url: str, **overrides: object) -> Engine:
    """Create an Engine with pool options appropriate for its database dialect."""
    options: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        "future": True,
    }
    if make_url(database_url).get_backend_name() != "sqlite":
        options.update(pool_size=10, max_overflow=20)
    options.update(overrides)
    return create_engine(database_url, **options)


engine = create_database_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts (commits on success, rolls back on error)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
