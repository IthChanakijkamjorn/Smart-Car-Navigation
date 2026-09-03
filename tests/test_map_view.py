"""Tests for the Map View data layer (Problem 2): image upload + marker positions.

Only the data layer is tested here (not visual rendering), as requested.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Destination, MapSettings, Signage


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    """Redirect uploaded map images to a throw-away directory for every test."""
    from app.routers import map_admin

    monkeypatch.setattr(map_admin, "UPLOAD_DIR", tmp_path / "uploads")


def test_map_upload_rejects_unsupported_file_type(client, db_session: Session) -> None:
    response = client.post(
        "/map/upload",
        files={"file": ("map.txt", b"not an image", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db_session.scalar(select(MapSettings)) is None or (
        db_session.scalar(select(MapSettings)).image_path is None
    )


def test_map_upload_stores_image_and_updates_settings(client, db_session: Session) -> None:
    response = client.post(
        "/map/upload",
        files={"file": ("map.png", b"\x89PNG\r\n\x1a\n fake png bytes", "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    settings = db_session.scalar(select(MapSettings))
    assert settings is not None
    assert settings.image_path is not None
    assert settings.image_path.startswith("uploads/site-map-")
    assert settings.image_path.endswith(".png")


def test_signage_position_update(client, db_session: Session, sample_setup: dict) -> None:
    signage = sample_setup["signage"]
    assert signage.map_x is None
    assert signage.map_y is None

    response = client.post(
        f"/signages/{signage.id}/position",
        data={"map_x": "12.5", "map_y": "80"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db_session.refresh(signage)
    assert signage.map_x == 12.5
    assert signage.map_y == 80.0


def test_signage_position_can_be_cleared(client, db_session: Session, sample_setup: dict) -> None:
    signage = sample_setup["signage"]
    signage.map_x = 10
    signage.map_y = 20
    db_session.commit()

    response = client.post(
        f"/signages/{signage.id}/position",
        data={"map_x": "", "map_y": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db_session.refresh(signage)
    assert signage.map_x is None
    assert signage.map_y is None


def test_destination_position_update(client, db_session: Session, sample_setup: dict) -> None:
    destination = sample_setup["destination"]

    response = client.post(
        f"/destinations/{destination.id}/position",
        data={"map_x": "30", "map_y": "40"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db_session.refresh(destination)
    assert destination.map_x == 30.0
    assert destination.map_y == 40.0


def test_dashboard_home_lists_placed_markers(client, db_session: Session) -> None:
    destination = Destination(name="Lot Z", map_x=50, map_y=50)
    signage = Signage(code="SIGN-MAP", name="Map test signage", map_x=10, map_y=10)
    db_session.add_all([destination, signage])
    db_session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "SIGN-MAP" in response.text
    assert "Lot Z" in response.text


def test_batch_update_map_positions(client, db_session: Session, sample_setup: dict) -> None:
    """Improvement 1: the batch endpoint used by the drag-and-drop marker UI."""
    signage = sample_setup["signage"]
    destination = sample_setup["destination"]

    response = client.post(
        "/map/positions",
        json=[
            {"type": "signage", "id": signage.id, "x": 12.5, "y": 87.25},
            {"type": "destination", "id": destination.id, "x": 40, "y": 60},
        ],
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 2

    db_session.refresh(signage)
    db_session.refresh(destination)
    assert signage.map_x == 12.5
    assert signage.map_y == 87.25
    assert destination.map_x == 40.0
    assert destination.map_y == 60.0


def test_batch_update_map_positions_ignores_unknown_id(
    client, db_session: Session, sample_setup: dict
) -> None:
    response = client.post(
        "/map/positions",
        json=[{"type": "signage", "id": 999999, "x": 10, "y": 10}],
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 0


def test_batch_update_map_positions_rejects_out_of_range_coordinates(
    client, db_session: Session, sample_setup: dict
) -> None:
    response = client.post(
        "/map/positions",
        json=[{"type": "signage", "id": sample_setup["signage"].id, "x": 150, "y": 10}],
    )
    assert response.status_code == 422
