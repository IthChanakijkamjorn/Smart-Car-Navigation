"""Camera webhook: ``POST /api/detections``.

This is the machine-to-machine entry point. A Dahua LPR camera is configured
(in its own web UI, under "Alarm Server"/event push) to POST a JSON body here
every time it reads a plate. There is no UI on this endpoint.

TODO (before real deployment): protect this endpoint, e.g. with a shared secret
header or by restricting it to the camera subnet at the firewall level.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import DetectionIn, DetectionOut

router = APIRouter(prefix="/api", tags=["detections"])


@router.post("/detections", response_model=DetectionOut)
async def receive_detection(
    detection: DetectionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> DetectionOut:
    """Receive a plate detection, log it and update the linked signage."""
    # Keep the untouched body for the audit trail (cameras often send extra
    # vendor-specific fields we do not model).
    try:
        raw_payload = await request.json()
    except Exception:  # pragma: no cover - body already parsed by FastAPI
        raw_payload = detection.model_dump(mode="json")

    result = services.process_detection(
        db,
        plate_number=detection.plate_number,
        camera_code=detection.camera_id,
        confidence=detection.confidence,
        raw_payload=raw_payload,
    )

    if result.matched and result.destination is not None:
        message = f"{result.destination.name}"
    else:
        message = services.UNREGISTERED_MESSAGE

    return DetectionOut(
        event_id=result.event.id,
        plate_number=detection.plate_number,
        matched=result.matched,
        destination=result.destination.name if result.destination else None,
        direction_hint=result.destination.direction_hint if result.destination else None,
        signage_code=result.signage.code if result.signage else None,
        message=message,
    )
