"""Sample data for local testing.

Creates a handful of destinations, one signage and one camera so you can try the
whole flow (simulate a camera event -> watch the signage page change) without
any physical hardware.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera, Destination, Signage, Vehicle, VehicleSource
from app.services import normalize_plate

SAMPLE_DESTINATIONS = [
    ("Lot A", "left"),
    ("Lot B", "right"),
    ("Lot C", "straight"),
]

SAMPLE_SIGNAGES = [
    ("SIGN-01", "Entrance signage", "Main gate, above the barrier", "Lot A, Lot B, Lot C"),
]

SAMPLE_CAMERAS = [
    ("CAM-ENTRANCE-01", "Entrance LPR camera", "Main gate", "SIGN-01"),
]

SAMPLE_VEHICLES = [
    ("AB1234", "Lot A", "Sample resident"),
    ("XY9999", "Lot B", "Sample tenant"),
]


def seed(db: Session) -> dict[str, int]:
    """Insert the sample rows that do not exist yet. Safe to run repeatedly."""
    created = {"destinations": 0, "signages": 0, "cameras": 0, "vehicles": 0}

    for name, direction in SAMPLE_DESTINATIONS:
        if db.scalar(select(Destination).where(Destination.name == name)) is None:
            db.add(Destination(name=name, direction_hint=direction))
            created["destinations"] += 1
    db.flush()

    for code, name, location, supported in SAMPLE_SIGNAGES:
        if db.scalar(select(Signage).where(Signage.code == code)) is None:
            db.add(
                Signage(
                    code=code, name=name, location=location, supported_directions=supported
                )
            )
            created["signages"] += 1
    db.flush()

    for code, name, location, signage_code in SAMPLE_CAMERAS:
        if db.scalar(select(Camera).where(Camera.code == code)) is None:
            signage = db.scalar(select(Signage).where(Signage.code == signage_code))
            db.add(
                Camera(
                    code=code,
                    name=name,
                    location=location,
                    linked_signage_id=signage.id if signage else None,
                )
            )
            created["cameras"] += 1
    db.flush()

    for plate, destination_name, notes in SAMPLE_VEHICLES:
        plate = normalize_plate(plate)
        if db.scalar(select(Vehicle).where(Vehicle.plate_number == plate)) is None:
            destination = db.scalar(
                select(Destination).where(Destination.name == destination_name)
            )
            if destination is not None:
                db.add(
                    Vehicle(
                        plate_number=plate,
                        destination_id=destination.id,
                        source=VehicleSource.CSV_IMPORT,
                        notes=notes,
                    )
                )
                created["vehicles"] += 1

    db.commit()
    return created
