"""Tests for the camera webhook and the signage polling endpoint."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectionEvent, SignageCurrentState, SignageRoute, Vehicle, VehicleSource


def _register(db: Session, plate: str, destination_id: int) -> None:
    db.add(
        Vehicle(
            plate_number=plate, destination_id=destination_id, source=VehicleSource.CSV_IMPORT
        )
    )
    db.commit()


def _add_route(
    db: Session, signage_id: int, destination_id: int, direction: str, display_label=None
) -> None:
    db.add(
        SignageRoute(
            signage_id=signage_id,
            destination_id=destination_id,
            direction=direction,
            display_label=display_label,
        )
    )
    db.commit()


def test_detection_updates_signage_state(client, db_session: Session, sample_setup: dict) -> None:
    _register(db_session, "AB1234", sample_setup["destination"].id)
    _add_route(db_session, sample_setup["signage"].id, sample_setup["destination"].id, "left")

    response = client.post(
        "/api/detections",
        json={"plateNumber": "ab-1234", "cameraID": "CAM-ENTRANCE-01", "confidence": 0.97},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["destination"] == "Lot A"
    assert body["direction"] == "left"
    assert body["route_configured"] is True
    assert body["signage_code"] == "SIGN-01"

    state = db_session.scalar(select(SignageCurrentState))
    assert state.current_destination_id == sample_setup["destination"].id
    assert state.current_plate_number == "AB1234"

    # The display page and its polling endpoint reflect the new state,
    # resolved from the per-signage route (not a fixed destination field).
    current = client.get("/api/signage/SIGN-01/current").json()
    assert current["state"] == "guiding"
    assert current["destination"] == "Lot A"
    assert current["direction"] == "left"

    page = client.get("/signage/SIGN-01")
    assert page.status_code == 200
    assert "SIGN-01" in page.text


def test_detection_matched_destination_without_route_falls_back(
    client, db_session: Session, sample_setup: dict
) -> None:
    """Problem 1 fallback: a signage that was never configured for this
    destination shows "See attendant" instead of guessing a direction."""
    _register(db_session, "AB1234", sample_setup["destination"].id)
    # Deliberately NOT adding a SignageRoute row.

    response = client.post(
        "/api/detections", json={"plateNumber": "AB1234", "cameraID": "CAM-ENTRANCE-01"}
    )
    body = response.json()
    assert body["matched"] is True
    assert body["route_configured"] is False
    assert body["direction"] is None
    assert body["message"] == "See attendant"

    current = client.get("/api/signage/SIGN-01/current").json()
    assert current["state"] == "unrouted"
    assert current["destination"] == "Lot A"
    assert current["message"] == "See attendant"


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
