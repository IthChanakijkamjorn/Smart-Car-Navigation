"""Shared pytest fixtures.

Every test runs against a throw-away in-memory SQLite database so nothing
touches the real ``data/smart_car_navigation.db`` file.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Must be set before app.database is imported for the first time.
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.models import Camera, Destination, Signage  # noqa: E402


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """A fresh in-memory database for a single test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # keep one connection so the in-memory DB survives
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session):
    """FastAPI test client wired to the same in-memory database."""
    from fastapi.testclient import TestClient

    from app.main import app

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_setup(db_session: Session) -> dict[str, object]:
    """One destination, one signage and one camera linked together."""
    destination = Destination(name="Lot A", direction_hint="left")
    signage = Signage(code="SIGN-01", name="Entrance signage")
    db_session.add_all([destination, signage])
    db_session.flush()

    camera = Camera(
        code="CAM-ENTRANCE-01", name="Entrance camera", linked_signage_id=signage.id
    )
    db_session.add(camera)
    db_session.commit()
    return {"destination": destination, "signage": signage, "camera": camera}
