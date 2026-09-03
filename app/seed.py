"""Sample data for local testing.

Creates a handful of destinations, TWO signages (to demonstrate Problem 1: the
same destination gets a different direction depending on which signage is
showing it) and one camera per signage, so you can try the whole flow
(simulate a camera event -> watch the signage page change) without any
physical hardware.

Also demonstrates the Improvement 2 "direction group" concept: several
destinations deliberately share the same direction bucket on SIGN-01 (Lot A
and Lot B are both "left"), and "Lot D" is intentionally left "unset" on
SIGN-02 to show what the "still needs configuring" warning bucket looks like
on the routing page.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera, Destination, Signage, SignageRoute, Vehicle, VehicleSource
from app.services import ensure_signage_routes, normalize_plate

SAMPLE_DESTINATIONS = ["Lot A", "Lot B", "Lot C", "Lot D"]

SAMPLE_SIGNAGES = [
    ("SIGN-01", "Entrance signage", "Main gate, above the barrier", "Lot A, Lot B, Lot C, Lot D"),
    ("SIGN-02", "Mid-road signage", "50m past the entrance", "Lot A, Lot B, Lot C"),
]

SAMPLE_CAMERAS = [
    ("CAM-ENTRANCE-01", "Entrance LPR camera", "Main gate", "SIGN-01"),
    ("CAM-MIDROAD-01", "Mid-road LPR camera", "50m past the entrance", "SIGN-02"),
]

# (signage_code, destination_name, direction, display_label) - the whole
# point of Problem 1 + Improvement 2: the SAME destination ("Lot A") gets a
# DIFFERENT direction depending on which signage the driver is looking at,
# and several destinations can share one direction "bucket" on the routing
# page (Lot A + Lot B are both "left" from SIGN-01). "Lot D" is intentionally
# left at its auto-created default ("unset") on SIGN-02 - i.e. simply not
# listed below for that signage - to demonstrate the fallback ("See
# attendant") when a signage hasn't been configured for a destination yet.
SAMPLE_ROUTES = [
    ("SIGN-01", "Lot A", "left", None),
    ("SIGN-01", "Lot B", "left", None),
    ("SIGN-01", "Lot C", "right", None),
    ("SIGN-01", "Lot D", "straight", None),
    ("SIGN-02", "Lot A", "straight", None),
    ("SIGN-02", "Lot B", "straight", "Lot B - past the second barrier"),
    ("SIGN-02", "Lot C", "left", None),
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

    new_signage_codes = set()
    for code, name, location, supported in SAMPLE_SIGNAGES:
        if db.scalar(select(Signage).where(Signage.code == code)) is None:
            db.add(
                Signage(
                    code=code, name=name, location=location, supported_directions=supported
                )
            )
            created["signages"] += 1
            new_signage_codes.add(code)
    db.flush()

    # Auto-create the "unset" base pairing for every destination on every
    # NEW signage (Improvement 2) - mirrors what admin.create_or_update_signage
    # does for signages added through the dashboard, so seeded signages behave
    # exactly the same way.
    for code in new_signage_codes:
        signage = db.scalar(select(Signage).where(Signage.code == code))
        if signage is not None:
            ensure_signage_routes(db, signage)
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

    # Every (signage, destination) row above already exists (created as
    # "unset" by ensure_signage_routes) - this loop only ever UPDATES the
    # direction/display_label for the pairs we want to demo pre-configured,
    # never creates a new row, consistent with the rule that pairings are
    # never manually added/removed.
    for signage_code, destination_name, direction, display_label in SAMPLE_ROUTES:
        signage = db.scalar(select(Signage).where(Signage.code == signage_code))
        destination = db.scalar(select(Destination).where(Destination.name == destination_name))
        if signage is None or destination is None:
            continue
        route = db.scalar(
            select(SignageRoute).where(
                SignageRoute.signage_id == signage.id,
                SignageRoute.destination_id == destination.id,
            )
        )
        if route is None:
            # Defensive fallback - normally unreachable thanks to
            # ensure_signage_routes above.
            route = SignageRoute(signage_id=signage.id, destination_id=destination.id)
            db.add(route)
        if route.direction == "unset":
            created["routes"] += 1
        route.direction = direction
        route.display_label = display_label
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
