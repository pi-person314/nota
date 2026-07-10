"""SQLAlchemy engine and session management.

This module is intentionally framework-free: it is imported both by the
Flask application and, standalone, by the MCP server process (which only
needs DATABASE_URL to talk to the same database as the web app).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


_engine = None
_SessionLocal: sessionmaker | None = None


def init_db(database_url: str) -> None:
    """Initialize the engine/session factory and create tables if needed.

    Safe to call multiple times; re-initializes the engine each time so
    tests can point at a fresh temporary database per test.
    """
    global _engine, _SessionLocal

    connect_args = {}
    if database_url.startswith("sqlite"):
        # Allow the session to be used across threads (Flask's dev server
        # and the per-score command lock both touch the DB from different
        # request threads).
        connect_args["check_same_thread"] = False

    _engine = create_engine(database_url, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    # Import models so they're registered on Base.metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(_engine)


def get_engine():
    if _engine is None:
        raise RuntimeError("init_db() must be called before get_engine()")
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy Session. Caller is responsible for closing it."""
    if _SessionLocal is None:
        raise RuntimeError("init_db() must be called before get_session()")
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
