"""FastAPI application entry point.

Run it locally with::

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

or with Docker::

    docker compose up --build

The three interfaces this app exposes:

* ``POST /api/detections``            - camera webhook (machine to machine)
* ``/``, ``/vehicles``, ``/logs`` ... - admin / guard dashboard (HTML)
* ``/signage/{signage_code}``         - full-screen display page for a screen
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import __version__
from app.database import get_db, init_db
from app.routers import admin, detections, signage
from app.schemas import SeedResult
from app.seed import seed
from app.templating import STATIC_DIR

app = FastAPI(
    title="Smart Car Navigation",
    version=__version__,
    description=(
        "On-premise parking guidance: Dahua LPR cameras -> this server -> MAXHUB "
        "signage. Interactive API docs are available at /docs."
    ),
)

# Create the SQLite tables on startup. For schema changes over time, switch to
# Alembic migrations (see README) instead of relying on this call.
init_db()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(detections.router)
app.include_router(signage.router)
app.include_router(admin.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    """Liveness probe - handy to check the box is up from another machine."""
    return {"status": "ok", "version": __version__}


@app.post("/api/seed", response_model=SeedResult, tags=["ops"])
def seed_sample_data(db: Session = Depends(get_db)) -> SeedResult:
    """Create sample destinations/signages/cameras/vehicles for local testing.

    Safe to call more than once: existing rows are left untouched.

    TODO (before real deployment): remove this endpoint or put it behind the
    admin authentication that still has to be added.
    """
    created = seed(db)
    return SeedResult(created=created, message="Sample data is ready. Open / to see it.")
