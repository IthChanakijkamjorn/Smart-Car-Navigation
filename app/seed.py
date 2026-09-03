"""Sample data for local testing.

Creates a handful of destinations, TWO signages (to demonstrate Problem 1: the
same destination gets a different direction depending on which signage is
showing it) and one camera per signage, so you can try the whole flow
(simulate a camera event -> watch the signage page change) without any
physical hardware.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera, Destination, Signage, SignageRoute, Vehicle, VehicleSource
from app.services import normalize_plate

SAMPLE_DESTINATIONS = ["Lot A", "Lot B", "Lot C"]

SAMPLE_SIGNAGES = [
    ("SIGN-01", "Entrance signage", "Main gate, above the barrier", "Lot A, Lot B, Lot C"),
    ("SIGN-02", "Mid-road signage", "50m past the entrance", "Lot A, Lot B"),
]

SAMPLE_CAMERAS = [
    ("CAM-ENTRANCE-01", "Entrance LPR camera", "Main gate", "SIGN-01"),
    ("CAM-MIDROAD-01", "Mid-road LPR camera", "50m past the entrance", "SIGN-02"),
]

# (signage_code, destination_name, direction) - this is the whole point of
# Problem 1: the SAME destination ("Lot A") gets a DIFFERENT direction
# depending on which signage the driver is looking at. "Lot C" is
# intentionally left unconfigured on SIGN-02 to demonstrate the fallback
# ("See attendant") when a signage hasn't been set up for a destination yet.
SAMPLE_ROUTES = [
    ("SIGN-01", "Lot A", "left", None),
    ("SIGN-01", "Lot B", "right", None),
    ("SIGN-01", "Lot C", "straight", None),
    ("SIGN-02", "Lot A", "straight", None),
    ("SIGN-02", "Lot B", "left", "Lot B - past the second barrier"),
]

SAMPLE_VEHICLES = [
    ("AB1234", "Lot A", "Sample resident"),
    ("XY9999", "Lot B", "Sample tenant"),
]


def seed(db: Session) -> dict[str, int]:
    """Insert the sample rows that do not exist yet. Safe to run repeatedly."""
    created = {"destinations": 0, "signages": 0, "cameras": 0, "routes": 0, "vehicles": 0}

    for name in SAMPLE_DESTINATIONS:
        if db.scalar(select(Destination).where(Destination.name == name)) is None:
            db.add(Destination(name=name))
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

    for signage_code, destination_name, direction, display_label in SAMPLE_ROUTES:
        signage = db.scalar(select(Signage).where(Signage.code == signage_code))
        destination = db.scalar(select(Destination).where(Destination.name == destination_name))
        if signage is None or destination is None:
            continue
        existing = db.scalar(
            select(SignageRoute).where(
                SignageRoute.signage_id == signage.id,
                SignageRoute.destination_id == destination.id,
            )
        )
        if existing is None:
            db.add(
                SignageRoute(
                    signage_id=signage.id,
                    destination_id=destination.id,
                    direction=direction,
                    display_label=display_label,
                )
            )
            created["routes"] += 1
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
