"""Core business logic, kept out of the routers so it is easy to unit-test.

Two things happen here:

* ``process_detection`` - the write path: a camera reported a plate, we log it,
  look it up, and update what the linked signage should display.
* ``parse_vehicles_csv`` / ``import_vehicles_csv`` - the bulk registration path.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Camera,
    DetectionEvent,
    Destination,
    MapSettings,
    Signage,
    SignageCurrentState,
    SignageRoute,
    Vehicle,
    VehicleSource,
    utcnow,
)

logger = logging.getLogger(__name__)

# How long a message stays on a screen before it falls back to the idle state.
# A car needs only a few seconds to drive past the sign, so ~15s is plenty.
DISPLAY_TTL_SECONDS = int(os.getenv("DISPLAY_TTL_SECONDS", "15"))

# Message shown when a detected plate is not registered. The guard is expected
# to add the vehicle manually from the dashboard.
UNREGISTERED_MESSAGE = os.getenv("UNREGISTERED_MESSAGE", "Please proceed to the guard booth")

# Message shown when the plate IS registered and matched to a destination, but
# nobody has configured a route (direction) for THIS signage yet. This is the
# "signage hasn't been configured for that destination" fallback from Problem 1.
UNROUTED_MESSAGE = os.getenv("UNROUTED_MESSAGE", "See attendant")

_PLATE_CLEANUP_RE = re.compile(r"[\s\-_.]+")


def normalize_plate(plate: str) -> str:
    """Normalise a plate so camera readings and stored plates always match.

    Removes spaces/dashes/dots/underscores and upper-cases the result::

        " ab-123 " -> "AB123"
    """
    return _PLATE_CLEANUP_RE.sub("", (plate or "").strip()).upper()


def find_vehicle_by_plate(db: Session, plate: str) -> Vehicle | None:
    """Look up a registered vehicle by (normalised) plate number."""
    normalized = normalize_plate(plate)
    if not normalized:
        return None
    return db.scalar(select(Vehicle).where(Vehicle.plate_number == normalized))


def resolve_signage_route(
    db: Session, signage_id: int, destination_id: int
) -> SignageRoute | None:
    """Find the per-signage direction configured for a destination.

    Returns ``None`` when this signage has never been configured for that
    destination - callers should fall back to ``UNROUTED_MESSAGE`` in that
    case (see ``build_display_message`` below).
    """
    return db.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage_id,
            SignageRoute.destination_id == destination_id,
        )
    )


def build_display_message(route: SignageRoute | None, destination: Destination) -> str:
    """The text shown on screen once a destination + signage route are known."""
    if route is None:
        return UNROUTED_MESSAGE
    if route.display_label:
        return route.display_label
    return f"{destination.name} - {route.direction}"


def set_signage_state(
    db: Session,
    signage: Signage,
    destination: Destination | None,
    plate_number: str | None = None,
) -> SignageCurrentState:
    """Create/update the "what should this screen show right now" row."""
    state = db.scalar(
        select(SignageCurrentState).where(SignageCurrentState.signage_id == signage.id)
    )
    if state is None:
        state = SignageCurrentState(signage_id=signage.id)
        db.add(state)

    state.current_destination_id = destination.id if destination else None
    state.current_plate_number = plate_number
    state.last_updated_at = utcnow()
    db.flush()
    return state


def is_state_expired(state: SignageCurrentState | None) -> bool:
    """True when the stored message is older than ``DISPLAY_TTL_SECONDS``."""
    if state is None or state.last_updated_at is None:
        return True
    last = state.last_updated_at
    if last.tzinfo is None:  # SQLite gives back naive datetimes
        last = last.replace(tzinfo=utcnow().tzinfo)
    return (utcnow() - last) > timedelta(seconds=DISPLAY_TTL_SECONDS)


@dataclass
class DetectionResult:
    """Outcome of processing one camera event (returned to the camera as JSON)."""

    event: DetectionEvent
    vehicle: Vehicle | None
    destination: Destination | None
    signage: Signage | None
    matched: bool
    route: SignageRoute | None = None


def process_detection(
    db: Session,
    *,
    plate_number: str,
    camera_code: str | None = None,
    confidence: float | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> DetectionResult:
    """Handle one plate detection pushed by a camera.

    Steps: log the raw event -> look up the plate -> resolve the destination ->
    look up the signage_route for (signage, destination) -> update the current
    display command of the signage linked to that camera.
    """
    camera = None
    if camera_code:
        camera = db.scalar(select(Camera).where(Camera.code == camera_code))

    vehicle = find_vehicle_by_plate(db, plate_number)
    destination = vehicle.destination if vehicle else None

    event = DetectionEvent(
        camera_id=camera.id if camera else None,
        plate_number=plate_number,
        matched_vehicle_id=vehicle.id if vehicle else None,
        matched_destination_id=destination.id if destination else None,
        confidence=confidence,
        raw_payload=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
    )
    db.add(event)

    signage = camera.signage if camera else None
    route: SignageRoute | None = None
    if signage is not None:
        if destination is not None:
            route = resolve_signage_route(db, signage.id, destination.id)
            if route is None:
                # This signage has never been told what direction to show for
                # this destination - log it so the guard/installer notices and
                # configures it on /signages/{id}/routes.
                logger.warning(
                    "No signage_route configured for signage=%s destination=%s "
                    "(showing fallback message)",
                    signage.code,
                    destination.name,
                )
        # Unregistered plates still update the screen: it switches to the
        # "unregistered" message so the driver knows to stop at the booth.
        set_signage_state(db, signage, destination, normalize_plate(plate_number))

    db.commit()
    db.refresh(event)
    return DetectionResult(
        event=event,
        vehicle=vehicle,
        destination=destination,
        signage=signage,
        matched=vehicle is not None,
        route=route,
    )


@dataclass
class CsvImportResult:
    """Summary of a CSV import, shown back to the guard after uploading."""

    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated


# Column names accepted in the uploaded CSV (case-insensitive).
CSV_PLATE_COLUMNS = ("plate_number", "plate", "license_plate")
CSV_DESTINATION_COLUMNS = ("destination_name", "destination", "lot")
CSV_NOTES_COLUMNS = ("notes", "note")


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    """Return the first non-empty value among ``names`` in a CSV row."""
    for name in names:
        value = row.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def parse_vehicles_csv(content: str) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV text into ``[{plate_number, destination_name, notes}, ...]``.

    Returns the valid rows plus a list of human readable error messages for the
    rows that had to be skipped. No database access happens here, which makes
    this function trivial to unit-test.
    """
    rows: list[dict[str, str]] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["The CSV file is empty or has no header row."]

    # Normalise the header so "Plate Number" and "plate_number" both work.
    reader.fieldnames = [(name or "").strip().lower().replace(" ", "_") for name in reader.fieldnames]

    for line_number, raw_row in enumerate(reader, start=2):  # line 1 is the header
        row = {(k or ""): (v or "") for k, v in raw_row.items() if k is not None}
        plate = normalize_plate(_pick(row, CSV_PLATE_COLUMNS))
        destination = _pick(row, CSV_DESTINATION_COLUMNS)

        if not plate and not destination:
            continue  # silently skip completely blank lines
        if not plate:
            errors.append(f"Line {line_number}: missing plate_number.")
            continue
        if not destination:
            errors.append(f"Line {line_number}: missing destination_name for plate {plate}.")
            continue

        rows.append(
            {
                "plate_number": plate,
                "destination_name": destination,
                "notes": _pick(row, CSV_NOTES_COLUMNS),
            }
        )

    return rows, errors


def get_or_create_destination(db: Session, name: str) -> Destination:
    """Find a destination by name, creating it if the CSV mentions a new one."""
    destination = db.scalar(select(Destination).where(Destination.name == name))
    if destination is None:
        destination = Destination(name=name)
        db.add(destination)
        db.flush()
    return destination


def import_vehicles_csv(
    db: Session, content: str, *, source: VehicleSource = VehicleSource.CSV_IMPORT
) -> CsvImportResult:
    """Parse and persist a vehicles CSV. Existing plates are updated in place."""
    rows, errors = parse_vehicles_csv(content)
    result = CsvImportResult(errors=list(errors))

    for row in rows:
        destination = get_or_create_destination(db, row["destination_name"])
        vehicle = db.scalar(
            select(Vehicle).where(Vehicle.plate_number == row["plate_number"])
        )
        if vehicle is None:
            db.add(
                Vehicle(
                    plate_number=row["plate_number"],
                    destination_id=destination.id,
                    source=source,
                    notes=row["notes"] or None,
                )
            )
            result.created += 1
        else:
            vehicle.destination_id = destination.id
            vehicle.source = source
            if row["notes"]:
                vehicle.notes = row["notes"]
            result.updated += 1

    db.commit()
    return result


# --------------------------------------------------------------------------- #
# Map View (Problem 2) - a single settings row holding the uploaded map image.
# --------------------------------------------------------------------------- #


def get_or_create_map_settings(db: Session) -> MapSettings:
    """Return the single ``MapSettings`` row, creating it on first use."""
    settings = db.scalar(select(MapSettings))
    if settings is None:
        settings = MapSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings
