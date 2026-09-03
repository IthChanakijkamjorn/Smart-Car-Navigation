"""Admin pages for Problem 1 (per-signage routing) and Problem 2 (Map View).

* ``/signages/{id}/routes``       - per-signage routing table (direction per
  destination) - the fix for "direction depends on which signage").
* ``/map/upload``                 - upload the background image for the Map View.
* ``/signages/{id}/position``     - set a signage's marker position on the map.
* ``/destinations/{id}/position`` - set a destination's marker position on the map.

Kept in its own router file (rather than growing ``admin.py`` further) so each
file stays focused on one concern.

TODO (before real deployment): same as admin.py - no login yet.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.models import Destination, RouteDirection, Signage, SignageRoute
from app.templating import STATIC_DIR, templates

router = APIRouter(tags=["admin", "map"])

UPLOAD_DIR = STATIC_DIR / "uploads"
# Only allow a small set of common image types for the site map.
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_MAP_IMAGE_BYTES = 8 * 1_024 * 1_024  # 8 MB is plenty for a floor-plan photo/scan


def _redirect(path: str, message: str = "") -> RedirectResponse:
    # All callers pass fixed literals or f-strings built from typed (int) path
    # params, never raw user text - but this helper double-checks that the
    # target is one of our own pages (starts with "/", no scheme/host part)
    # so it can never be turned into an open redirect, even by a future caller.
    if "://" in path or path.startswith("//") or not path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid redirect path")
    url = f"{path}?{urlencode({'message': message})}" if message else path
    return RedirectResponse(url, status_code=303)


def _get_signage_or_404(db: Session, signage_id: int) -> Signage:
    signage = db.get(Signage, signage_id)
    if signage is None:
        raise HTTPException(status_code=404, detail="Unknown signage")
    return signage


def _get_destination_or_404(db: Session, destination_id: int) -> Destination:
    destination = db.get(Destination, destination_id)
    if destination is None:
        raise HTTPException(status_code=404, detail="Unknown destination")
    return destination


# --------------------------------------------------------------------------- #
# Problem 1: per-signage routing table
# --------------------------------------------------------------------------- #


@router.get("/signages/{signage_id}/routes", response_class=HTMLResponse)
def signage_routes_page(
    signage_id: int, request: Request, message: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    """Show every destination with the direction (if any) configured for it
    on THIS signage - the "routing table" for one screen."""
    signage = _get_signage_or_404(db, signage_id)
    destinations = list(db.scalars(select(Destination).order_by(Destination.name)))
    routes_by_destination = {
        route.destination_id: route
        for route in db.scalars(select(SignageRoute).where(SignageRoute.signage_id == signage_id))
    }
    return templates.TemplateResponse(
        request,
        "dashboard/routes.html",
        {
            "signage": signage,
            "destinations": destinations,
            "routes_by_destination": routes_by_destination,
            "directions": [d.value for d in RouteDirection],
            "message": message,
            "active": "signages",
        },
    )


@router.post("/signages/{signage_id}/routes")
def save_signage_route(
    signage_id: int,
    destination_id: int = Form(...),
    direction: str = Form(...),
    display_label: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Create/update the route for one (signage, destination) pair."""
    signage = _get_signage_or_404(db, signage_id)
    destination = _get_destination_or_404(db, destination_id)

    route = db.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage.id,
            SignageRoute.destination_id == destination.id,
        )
    )
    if route is None:
        route = SignageRoute(signage_id=signage.id, destination_id=destination.id)
        db.add(route)
    route.direction = direction.strip() or "straight"
    route.display_label = display_label.strip() or None
    db.commit()
    return _redirect(
        f"/signages/{signage_id}/routes", f"Saved route for {destination.name}"
    )


@router.post("/signages/{signage_id}/routes/{destination_id}/delete")
def delete_signage_route(
    signage_id: int, destination_id: int, db: Session = Depends(get_db)
) -> RedirectResponse:
    """Remove a route so this signage falls back to the "See attendant" message."""
    route = db.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage_id,
            SignageRoute.destination_id == destination_id,
        )
    )
    if route is not None:
        db.delete(route)
        db.commit()
    return _redirect(f"/signages/{signage_id}/routes", "Route removed")


# --------------------------------------------------------------------------- #
# Problem 2: Map View - image upload + marker positions
# --------------------------------------------------------------------------- #


@router.get("/map/upload", response_class=HTMLResponse)
def map_upload_form(
    request: Request, message: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    """Show the current map image (if any) and the upload form."""
    map_settings = services.get_or_create_map_settings(db)
    return templates.TemplateResponse(
        request,
        "dashboard/map_upload.html",
        {"map_settings": map_settings, "message": message, "active": "dashboard"},
    )


@router.post("/map/upload")
async def map_upload_submit(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    """Save the uploaded image under static/uploads/ and remember its path."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return _redirect(
            "/map/upload",
            f"Unsupported file type '{extension}'. Use PNG, JPG, GIF or WEBP.",
        )

    raw = await file.read()
    if len(raw) > MAX_MAP_IMAGE_BYTES:
        return _redirect("/map/upload", "Image is too large (limit: 8 MB).")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Random filename: avoids clashes/overwrites and any path-traversal risk
    # from the original filename.
    stored_name = f"site-map-{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / stored_name).write_bytes(raw)

    map_settings = services.get_or_create_map_settings(db)
    map_settings.image_path = f"uploads/{stored_name}"
    db.commit()
    return _redirect("/", "Map image uploaded")


@router.get("/signages/{signage_id}/position", response_class=HTMLResponse)
def signage_position_form(
    signage_id: int, request: Request, message: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    signage = _get_signage_or_404(db, signage_id)
    return templates.TemplateResponse(
        request,
        "dashboard/position.html",
        {
            "kind": "signage",
            "item": signage,
            "action": f"/signages/{signage_id}/position",
            "message": message,
            "active": "dashboard",
        },
    )


def _parse_coordinate(value: str) -> float | None:
    """Parse a map_x/map_y form field; blank means "remove from the map"."""
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Position must be a number (0-100).") from None


@router.post("/signages/{signage_id}/position")
def signage_position_submit(
    signage_id: int,
    map_x: str = Form(""),
    map_y: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    signage = _get_signage_or_404(db, signage_id)
    signage.map_x = _parse_coordinate(map_x)
    signage.map_y = _parse_coordinate(map_y)
    db.commit()
    return _redirect("/", f"Saved map position for {signage.code}")


@router.get("/destinations/{destination_id}/position", response_class=HTMLResponse)
def destination_position_form(
    destination_id: int, request: Request, message: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    destination = _get_destination_or_404(db, destination_id)
    return templates.TemplateResponse(
        request,
        "dashboard/position.html",
        {
            "kind": "destination",
            "item": destination,
            "action": f"/destinations/{destination_id}/position",
            "message": message,
            "active": "dashboard",
        },
    )


@router.post("/destinations/{destination_id}/position")
def destination_position_submit(
    destination_id: int,
    map_x: str = Form(""),
    map_y: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    destination = _get_destination_or_404(db, destination_id)
    destination.map_x = _parse_coordinate(map_x)
    destination.map_y = _parse_coordinate(map_y)
    db.commit()
    return _redirect("/", f"Saved map position for {destination.name}")
