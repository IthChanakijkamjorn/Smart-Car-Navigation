"""SQLAlchemy ORM models.

Entity overview::

    destinations  <-- vehicles          (where a plate should be sent)
    destinations  <-- signage_current_state
    signages      <-- cameras           (a camera updates one signage)
    cameras       <-- detection_events  (raw audit trail of every plate read)

Everything is plain SQLAlchemy ORM so the same models work on SQLite (today) and
PostgreSQL (later) without changes.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """Timezone-aware "now", used as the default for every timestamp column."""
    return datetime.now(timezone.utc)


class VehicleSource(str, enum.Enum):
    """How a vehicle record got into the system."""

    CSV_IMPORT = "csv_import"  # pre-registered tenants/residents, bulk uploaded
    MANUAL_GUARD = "manual_guard"  # typed in by a security guard at the gate


class Destination(Base):
    """A place a car can be routed to, e.g. "Lot A"."""

    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    # Free text hint used by the signage page to pick an arrow: left/right/straight.
    direction_hint: Mapped[str] = mapped_column(String(20), default="straight", nullable=False)
    # NOTE: capacity/occupancy fields (e.g. capacity, current_occupancy) can be
    # added here later without touching any other table.

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="destination")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Destination {self.name} ({self.direction_hint})>"


class Vehicle(Base):
    """A license plate mapped to the destination it should be guided to."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Plates are always stored normalised (upper-case, no spaces/dashes) so that
    # camera readings match regardless of formatting - see services.normalize_plate.
    plate_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), nullable=False)
    source: Mapped[VehicleSource] = mapped_column(
        Enum(VehicleSource), default=VehicleSource.MANUAL_GUARD, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    destination: Mapped[Destination] = relationship(back_populates="vehicles")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Vehicle {self.plate_number}>"


class Signage(Base):
    """A MAXHUB screen (or any browser in kiosk mode) showing directions."""

    __tablename__ = "signages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Short human/URL friendly code, used in /signage/{code}, e.g. "SIGN-01".
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Free text description of what this screen is able to display, e.g.
    # "left/right" or "Lot A, Lot B, Lot C". Kept as text on purpose so the
    # guard can describe the physical screen without a rigid schema.
    supported_directions: Mapped[str | None] = mapped_column(Text, nullable=True)

    cameras: Mapped[list["Camera"]] = relationship(back_populates="signage")
    current_state: Mapped["SignageCurrentState | None"] = relationship(
        back_populates="signage", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Signage {self.code}>"


class Camera(Base):
    """A Dahua LPR camera pushing detections to POST /api/detections."""

    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Must match the camera ID the device sends in its event payload.
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Which screen this camera's detections should update.
    linked_signage_id: Mapped[int | None] = mapped_column(
        ForeignKey("signages.id"), nullable=True
    )

    signage: Mapped[Signage | None] = relationship(back_populates="cameras")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Camera {self.code}>"


class DetectionEvent(Base):
    """Raw audit trail: one row per plate read received from a camera.

    Never delete rows here - it is the evidence trail used to debug "why did the
    screen show that?" questions.
    """

    __tablename__ = "detection_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    # Plate exactly as received from the camera (not normalised).
    plate_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    matched_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id"), nullable=True
    )
    matched_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id"), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Full JSON body as sent by the camera, stored as text for portability.
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    camera: Mapped[Camera | None] = relationship()
    matched_vehicle: Mapped[Vehicle | None] = relationship()
    matched_destination: Mapped[Destination | None] = relationship()


class SignageCurrentState(Base):
    """What a given signage should be displaying right now.

    The signage page polls this (via the JSON API) once per second. Writing a row
    here is the only thing the detection webhook needs to do to "push" a message
    to a screen.
    """

    __tablename__ = "signage_current_state"
    __table_args__ = (UniqueConstraint("signage_id", name="uq_signage_current_state_signage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signage_id: Mapped[int] = mapped_column(ForeignKey("signages.id"), nullable=False)
    current_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id"), nullable=True
    )
    # Plate that triggered the current message (handy on screen + for debugging).
    current_plate_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    signage: Mapped[Signage] = relationship(back_populates="current_state")
    current_destination: Mapped[Destination | None] = relationship()
