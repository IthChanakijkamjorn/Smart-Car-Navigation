"""Tests for the camera webhook and the signage polling endpoint."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectionEvent, SignageCurrentState, Vehicle, VehicleSource


def _register(db: Session, plate: str, destination_id: int) -> None:
    db.add(
        Vehicle(
            plate_number=plate, destination_id=destination_id, source=VehicleSource.CSV_IMPORT
        )
    )
    db.commit()


def test_detection_updates_signage_state(client, db_session: Session, sample_setup: dict) -> None:
    _register(db_session, "AB1234", sample_setup["destination"].id)

    response = client.post(
        "/api/detections",
        json={"plateNumber": "ab-1234", "cameraID": "CAM-ENTRANCE-01", "confidence": 0.97},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["destination"] == "Lot A"
    assert body["signage_code"] == "SIGN-01"

    state = db_session.scalar(select(SignageCurrentState))
    assert state.current_destination_id == sample_setup["destination"].id
    assert state.current_plate_number == "AB1234"

    # The display page and its polling endpoint reflect the new state.
    current = client.get("/api/signage/SIGN-01/current").json()
    assert current["state"] == "guiding"
    assert current["destination"] == "Lot A"
    assert current["direction_hint"] == "left"

    page = client.get("/signage/SIGN-01")
    assert page.status_code == 200
    assert "SIGN-01" in page.text


def test_detection_of_unregistered_plate_is_logged(
    client, db_session: Session, sample_setup: dict
) -> None:
    response = client.post(
        "/api/detections", json={"plateNumber": "ZZ0000", "cameraID": "CAM-ENTRANCE-01"}
    )

    assert response.status_code == 200
    assert response.json()["matched"] is False

    event = db_session.scalar(select(DetectionEvent))
    assert event.plate_number == "ZZ0000"
    assert event.matched_vehicle_id is None
    assert event.raw_payload is not None

    current = client.get("/api/signage/SIGN-01/current").json()
    assert current["state"] == "unregistered"
    assert current["destination"] is None


def test_detection_from_unknown_camera_is_still_logged(client, db_session: Session) -> None:
    response = client.post("/api/detections", json={"plateNumber": "AB1234"})

    assert response.status_code == 200
    assert response.json()["signage_code"] is None
    assert db_session.scalar(select(DetectionEvent)).camera_id is None


def test_signage_idle_state_and_unknown_signage(client, sample_setup: dict) -> None:
    current = client.get("/api/signage/SIGN-01/current").json()
    assert current["state"] == "idle"
    assert client.get("/api/signage/NOPE/current").status_code == 404


def test_state_expires_back_to_idle(
    client, db_session: Session, sample_setup: dict, monkeypatch
) -> None:
    from app import services

    monkeypatch.setattr(services, "DISPLAY_TTL_SECONDS", 0)
    _register(db_session, "AB1234", sample_setup["destination"].id)
    client.post(
        "/api/detections", json={"plateNumber": "AB1234", "cameraID": "CAM-ENTRANCE-01"}
    )

    assert client.get("/api/signage/SIGN-01/current").json()["state"] == "idle"
