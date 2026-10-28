"""SQLAlchemy engine / session setup for the SQLite persistence layer.

SQLite only (per Phase 10). The database URL is resolved once, in this order:
  1. the MUN_DATABASE_URL environment variable, if set (any SQLAlchemy URL — this is also the seam
     through which a future PostgreSQL deployment is configured, without changing MUN logic);
  2. otherwise a local SQLite file at <repo root>/mun.db.

Tests pass an explicit in-memory URL ("sqlite://") so they never touch disk.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = REPO_ROOT / "mun.db"


class Base(DeclarativeBase):
    """Declarative base for every ORM table in this package."""


def resolve_database_url(url: Optional[str] = None) -> str:
    if url:
        return url
    env = os.getenv("MUN_DATABASE_URL", "").strip()
    if env:
        return env
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def create_db_engine(url: Optional[str] = None) -> Engine:
    """A SQLAlchemy engine for the given/resolved URL.

    For SQLite we disable the same-thread check because FastAPI runs sync routes in a thread pool,
    and use a StaticPool for the in-memory database so every session shares the one connection
    (otherwise ``sqlite://`` would give each connection its own empty database).
    """
    resolved = resolve_database_url(url)
    connect_args = {}
    engine_kwargs = {}
    if resolved.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in resolved or resolved in ("sqlite://", "sqlite:///:memory:"):
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
    return create_engine(resolved, future=True, connect_args=connect_args, **engine_kwargs)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create every table if it does not already exist (idempotent)."""
    # Import the ORM models so they are registered on Base.metadata before create_all.
    from . import models_orm  # noqa: F401

    Base.metadata.create_all(engine)
