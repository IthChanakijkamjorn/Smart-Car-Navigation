"""Pydantic schemas for the machine-to-machine JSON APIs.

Only the camera webhook and the signage polling endpoint need schemas; the admin
dashboard uses plain HTML forms.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DetectionIn(BaseModel):
    """Payload pushed by a Dahua LPR camera ("Alarm Server" HTTP push).

    Dahua firmware versions use slightly different field names, so the common
    spellings are accepted as aliases. Extra fields are kept and stored in
    ``detection_events.raw_payload`` for auditing.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    plate_number: str = Field(
        ...,
        validation_alias="plateNumber",
        serialization_alias="plateNumber",
        description="License plate text as read by the camera.",
    )
    camera_id: str | None = Field(
        default=None,
        validation_alias="cameraID",
        description="Camera code, must match a camera configured in the dashboard.",
    )
    timestamp: datetime | None = Field(default=None, description="Camera-side event time.")
    confidence: float | None = Field(default=None, description="Recognition confidence 0-1.")
    snapshot_base64: str | None = Field(
        default=None,
        validation_alias="snapshotBase64",
        description="Optional JPEG snapshot; currently logged only, not stored as a file.",
    )


class DetectionOut(BaseModel):
    """What the webhook answers to the camera (useful when testing with curl)."""

    event_id: int
    plate_number: str
    matched: bool
    destination: str | None = None
    direction: str | None = None
    route_configured: bool = False
    signage_code: str | None = None
    message: str


class SignageCurrentOut(BaseModel):
    """Payload polled every second by the signage display page."""

    signage_id: int
    signage_code: str
    signage_name: str
    state: str = Field(description="'idle', 'guiding', 'unrouted' or 'unregistered'")
    destination: str | None = None
    direction: str | None = None
    route_configured: bool = False
    plate_number: str | None = None
    message: str
    last_updated_at: datetime | None = None
    server_time: datetime
    poll_interval_ms: int = 1000


class SeedResult(BaseModel):
    """Result of POST /api/seed (sample data for local testing)."""

    created: dict[str, Any]
    message: str


class MapPositionUpdate(BaseModel):
    """One marker's new position, as dragged on the Map View (Improvement 1).

    Sent as a JSON array of these to ``POST /map/positions`` - one batch
    request covers every marker the admin moved before clicking "Save
    positions", instead of saving on every single drag.
    """

    type: Literal["signage", "destination"]
    id: int
    x: float = Field(ge=0, le=100, description="Percentage of the map image's width.")
    y: float = Field(ge=0, le=100, description="Percentage of the map image's height.")
