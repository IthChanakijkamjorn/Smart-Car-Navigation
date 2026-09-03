"""Database setup (SQLAlchemy ORM).

We use SQLite by default because the system runs on a single on-site mini PC and
SQLite needs zero administration. Everything is written with the SQLAlchemy ORM
(no SQLite-specific SQL), so moving to PostgreSQL later is only a matter of
changing the ``DATABASE_URL`` environment variable, e.g.::

    DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/parking
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Where the SQLite file lives. Inside Docker this path is mounted on a named
# volume so the data survives container restarts (see docker-compose.yml).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/smart_car_navigation.db")

# ``check_same_thread`` is a SQLite-only flag; FastAPI serves requests from a
# thread pool, so we must disable SQLite's single-thread guard.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

if DATABASE_URL.startswith("sqlite:///./"):
    # Make sure the folder holding the SQLite file exists before connecting.
    os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///./", "")) or ".", exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency that hands a database session to a request handler."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not exist yet.

    This is the "simple" alternative to Alembic migrations. It is enough for the
    first version; once the schema starts changing in production, add Alembic
    (see README) and stop calling this at startup.
    """
    from app import models  # noqa: F401  (imported for its side effect: model registration)

    Base.metadata.create_all(bind=engine)
