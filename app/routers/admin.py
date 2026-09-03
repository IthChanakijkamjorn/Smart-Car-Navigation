"""Admin / guard dashboard (server-rendered HTML, no JavaScript framework).

Everything a human touches lives here:

* ``/`` - overview
* ``/vehicles`` - list/search + manual entry form + edit/delete
* ``/csv-import`` - bulk import of registered plates
* ``/logs`` - detection event history
* ``/signages`` - signage + camera management

TODO (before real deployment): there is no login yet. Add simple session-based
authentication in front of every route in this router.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.models import (
    Camera,
    DetectionEvent,
    Destination,
    Signage,
    SignageCurrentState,
    Vehicle,
    VehicleSource,
)
from app.templating import templates

router = APIRouter(tags=["admin"])

# Maximum accepted size of an uploaded CSV (1 MB is ~20k plates).
MAX_CSV_BYTES = 1_024 * 1_024


def _redirect(path: str, message: str = "") -> RedirectResponse:
    """Redirect back to a dashboard page with a status message.

    The message is URL-encoded so user supplied text (plate numbers, names)
    can never break out of the query string.
    """
    url = f"{path}?{urlencode({'message': message})}" if message else path
    return RedirectResponse(url, status_code=303)


def _destinations(db: Session) -> list[Destination]:
    return list(db.scalars(select(Destination).order_by(Destination.name)))


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Overview page with a few counters and the list of signage links."""
    stats = {
        "vehicles": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
        "destinations": db.scalar(select(func.count()).select_from(Destination)) or 0,
        "signages": db.scalar(select(func.count()).select_from(Signage)) or 0,
        "cameras": db.scalar(select(func.count()).select_from(Camera)) or 0,
        "events": db.scalar(select(func.count()).select_from(DetectionEvent)) or 0,
    }
    recent_events = list(
        db.scalars(select(DetectionEvent).order_by(DetectionEvent.created_at.desc()).limit(10))
    )
    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "stats": stats,
            "recent_events": recent_events,
            "signages": list(db.scalars(select(Signage).order_by(Signage.code))),
            "active": "dashboard",
        },
    )


# --------------------------------------------------------------------------- #
# Vehicles (registered plates)
# --------------------------------------------------------------------------- #


@router.get("/vehicles", response_class=HTMLResponse)
def list_vehicles(
    request: Request,
    q: str = "",
    message: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """List/search registered plates and show the manual entry form."""
    stmt = select(Vehicle).order_by(Vehicle.plate_number)
    if q.strip():
        # Search on the normalised plate so "ab 123" finds "AB123".
        stmt = stmt.where(Vehicle.plate_number.contains(services.normalize_plate(q)))
    return templates.TemplateResponse(
        request,
        "dashboard/vehicles.html",
        {
            "vehicles": list(db.scalars(stmt)),
            "destinations": _destinations(db),
            "q": q,
            "message": message,
            "active": "vehicles",
        },
    )


@router.post("/vehicles")
def create_or_update_vehicle(
    plate_number: str = Form(...),
    destination_id: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Manual entry by the guard. Re-submitting a plate updates it."""
    plate = services.normalize_plate(plate_number)
    if not plate:
        return _redirect("/vehicles", "Plate number is required")

    destination = db.get(Destination, destination_id)
    if destination is None:
        return _redirect("/vehicles", "Unknown destination")

    vehicle = db.scalar(select(Vehicle).where(Vehicle.plate_number == plate))
    if vehicle is None:
        db.add(
            Vehicle(
                plate_number=plate,
                destination_id=destination.id,
                source=VehicleSource.MANUAL_GUARD,
                notes=notes or None,
            )
        )
        message = f"Added {plate} -> {destination.name}"
    else:
        vehicle.destination_id = destination.id
        vehicle.notes = notes or None
        message = f"Updated {plate} -> {destination.name}"
    db.commit()
    return _redirect("/vehicles", message)


@router.post("/vehicles/{vehicle_id}/delete")
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    """Remove a registered plate."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is not None:
        db.delete(vehicle)
        db.commit()
    return _redirect("/vehicles", "Vehicle deleted")


# --------------------------------------------------------------------------- #
# CSV import
# --------------------------------------------------------------------------- #


@router.get("/csv-import", response_class=HTMLResponse)
def csv_import_form(request: Request) -> HTMLResponse:
    """Show the upload form and the expected column names."""
    return templates.TemplateResponse(
        request, "dashboard/csv_import.html", {"result": None, "active": "csv_import"}
    )


@router.post("/csv-import", response_class=HTMLResponse)
async def csv_import_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Parse the uploaded CSV and create/update the vehicles it contains."""
    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large (limit: 1 MB).")
    try:
        content = raw.decode("utf-8-sig")  # utf-8-sig strips Excel's BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.") from None

    result = services.import_vehicles_csv(db, content)
    return templates.TemplateResponse(
        request,
        "dashboard/csv_import.html",
        {"result": result, "filename": file.filename, "active": "csv_import"},
    )


# --------------------------------------------------------------------------- #
# Detection logs
# --------------------------------------------------------------------------- #


@router.get("/logs", response_class=HTMLResponse)
def detection_logs(
    request: Request,
    q: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Raw camera event history: what was read and what was displayed."""
    limit = max(1, min(limit, 1000))
    stmt = select(DetectionEvent).order_by(DetectionEvent.created_at.desc()).limit(limit)
    if q.strip():
        stmt = stmt.where(DetectionEvent.plate_number.contains(q.strip()))
    return templates.TemplateResponse(
        request,
        "dashboard/logs.html",
        {"events": list(db.scalars(stmt)), "q": q, "limit": limit, "active": "logs"},
    )


# --------------------------------------------------------------------------- #
# Signages, cameras and destinations
# --------------------------------------------------------------------------- #


@router.get("/signages", response_class=HTMLResponse)
def list_signages(
    request: Request, message: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    """Manage screens, cameras and destinations on one page."""
    return templates.TemplateResponse(
        request,
        "dashboard/signages.html",
        {
            "signages": list(db.scalars(select(Signage).order_by(Signage.code))),
            "cameras": list(db.scalars(select(Camera).order_by(Camera.code))),
            "destinations": _destinations(db),
            "message": message,
            "active": "signages",
        },
    )


@router.post("/signages")
def create_or_update_signage(
    code: str = Form(...),
    name: str = Form(...),
    location: str = Form(""),
    supported_directions: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Add a screen, or update it when the same code is submitted again."""
    code = code.strip()
    if not code:
        return _redirect("/signages", "Signage code is required")

    signage = db.scalar(select(Signage).where(Signage.code == code))
    if signage is None:
        signage = Signage(code=code)
        db.add(signage)
    signage.name = name.strip() or code
    signage.location = location.strip() or None
    signage.supported_directions = supported_directions.strip() or None
    db.commit()
    return _redirect("/signages", f"Saved signage {code}")


@router.post("/signages/{signage_id}/delete")
def delete_signage(signage_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    """Delete a screen (cameras pointing at it are simply unlinked)."""
    signage = db.get(Signage, signage_id)
    if signage is not None:
        for camera in signage.cameras:
            camera.linked_signage_id = None
        db.delete(signage)
        db.commit()
    return _redirect("/signages", "Signage deleted")


@router.post("/cameras")
def create_or_update_camera(
    code: str = Form(...),
    name: str = Form(...),
    location: str = Form(""),
    linked_signage_id: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Register a camera. ``code`` must match the ID the camera pushes."""
    code = code.strip()
    if not code:
        return _redirect("/signages", "Camera code is required")

    camera = db.scalar(select(Camera).where(Camera.code == code))
    if camera is None:
        camera = Camera(code=code)
        db.add(camera)
    camera.name = name.strip() or code
    camera.location = location.strip() or None
    camera.linked_signage_id = int(linked_signage_id) if linked_signage_id.strip() else None
    db.commit()
    return _redirect("/signages", f"Saved camera {code}")


@router.post("/cameras/{camera_id}/delete")
def delete_camera(camera_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    """Delete a camera (its past detection events are kept)."""
    camera = db.get(Camera, camera_id)
    if camera is not None:
        db.delete(camera)
        db.commit()
    return _redirect("/signages", "Camera deleted")


@router.post("/destinations")
def create_or_update_destination(
    name: str = Form(...),
    direction_hint: str = Form("straight"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Add or update a destination (e.g. "Lot A" shown with a left arrow)."""
    name = name.strip()
    if not name:
        return _redirect("/signages", "Destination name is required")

    destination = db.scalar(select(Destination).where(Destination.name == name))
    if destination is None:
        destination = Destination(name=name)
        db.add(destination)
    destination.direction_hint = direction_hint.strip() or "straight"
    db.commit()
    return _redirect("/signages", f"Saved destination {name}")


@router.post("/destinations/{destination_id}/delete")
def delete_destination(destination_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    """Delete a destination, but only when no vehicle still points at it."""
    destination = db.get(Destination, destination_id)
    if destination is None:
        return _redirect("/signages", "Destination deleted")

    in_use = db.scalar(
        select(func.count()).select_from(Vehicle).where(Vehicle.destination_id == destination_id)
    )
    if in_use:
        return _redirect(
            "/signages",
            f"Cannot delete {destination.name}: {in_use} vehicle(s) still use it",
        )

    # Clear the destination from any screen currently displaying it.
    for state in db.scalars(
        select(SignageCurrentState).where(
            SignageCurrentState.current_destination_id == destination_id
        )
    ):
        state.current_destination_id = None
    db.delete(destination)
    db.commit()
    return _redirect("/signages", "Destination deleted")
