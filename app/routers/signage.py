"""Signage display page + the JSON endpoint that page polls.

``GET /signage/{signage_code}`` is what you point the MAXHUB screen's browser at
(kiosk/fullscreen mode). It contains a small piece of vanilla JS that calls
``GET /api/signage/{signage_code}/current`` once per second and re-renders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.models import Signage, SignageCurrentState
from app.schemas import SignageCurrentOut
from app.services import DISPLAY_TTL_SECONDS, UNREGISTERED_MESSAGE
from app.templating import templates

router = APIRouter(tags=["signage"])

IDLE_MESSAGE = "Welcome - please drive slowly"


def _get_signage(db: Session, signage_code: str) -> Signage:
    """Look up a signage by its code (e.g. "SIGN-01") or raise 404."""
    signage = db.scalar(select(Signage).where(Signage.code == signage_code))
    if signage is None:
        raise HTTPException(status_code=404, detail=f"Unknown signage '{signage_code}'")
    return signage


def build_current_payload(db: Session, signage: Signage) -> SignageCurrentOut:
    """Build the payload the display page renders."""
    state = db.scalar(
        select(SignageCurrentState).where(SignageCurrentState.signage_id == signage.id)
    )

    if state is None or services.is_state_expired(state):
        # Nothing recent to show: fall back to the idle/default screen.
        return SignageCurrentOut(
            signage_id=signage.id,
            signage_code=signage.code,
            signage_name=signage.name,
            state="idle",
            message=IDLE_MESSAGE,
            last_updated_at=state.last_updated_at if state else None,
            server_time=services.utcnow(),
        )

    destination = state.current_destination
    if destination is None:
        # A plate was detected but it is not registered.
        return SignageCurrentOut(
            signage_id=signage.id,
            signage_code=signage.code,
            signage_name=signage.name,
            state="unregistered",
            plate_number=state.current_plate_number,
            message=UNREGISTERED_MESSAGE,
            last_updated_at=state.last_updated_at,
            server_time=services.utcnow(),
        )

    # Direction now comes from the signage_route configured for THIS signage +
    # destination, not from a global field on the destination (Problem 1).
    route = services.resolve_signage_route(db, signage.id, destination.id)
    if route is None:
        return SignageCurrentOut(
            signage_id=signage.id,
            signage_code=signage.code,
            signage_name=signage.name,
            state="unrouted",
            destination=destination.name,
            plate_number=state.current_plate_number,
            message=services.UNROUTED_MESSAGE,
            route_configured=False,
            last_updated_at=state.last_updated_at,
            server_time=services.utcnow(),
        )

    return SignageCurrentOut(
        signage_id=signage.id,
        signage_code=signage.code,
        signage_name=signage.name,
        state="guiding",
        destination=destination.name,
        direction=route.direction,
        route_configured=True,
        plate_number=state.current_plate_number,
        message=services.build_display_message(route, destination),
        last_updated_at=state.last_updated_at,
        server_time=services.utcnow(),
    )


@router.get("/api/signage/{signage_code}/current", response_model=SignageCurrentOut)
def signage_current(signage_code: str, db: Session = Depends(get_db)) -> SignageCurrentOut:
    """JSON endpoint polled every second by the display page."""
    return build_current_payload(db, _get_signage(db, signage_code))


@router.get("/signage/{signage_code}", response_class=HTMLResponse)
def signage_display(
    signage_code: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    """Full-screen display page for one signage."""
    signage = _get_signage(db, signage_code)
    return templates.TemplateResponse(
        request,
        "signage/display.html",
        {
            "signage": signage,
            "initial": build_current_payload(db, signage).model_dump(mode="json"),
            "ttl_seconds": DISPLAY_TTL_SECONDS,
        },
    )
