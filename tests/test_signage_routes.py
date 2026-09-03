"""Tests for Problem 1 (per-signage routing) service logic and admin pages."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Destination, Signage, SignageRoute
from app.services import UNROUTED_MESSAGE, build_display_message, resolve_signage_route


def test_resolve_signage_route_returns_none_when_not_configured(
    db_session: Session, sample_setup: dict
) -> None:
    assert (
        resolve_signage_route(db_session, sample_setup["signage"].id, sample_setup["destination"].id)
        is None
    )


def test_same_destination_can_have_different_direction_per_signage(db_session: Session) -> None:
    """The whole point of Problem 1: two signages, one destination, two directions."""
    destination = Destination(name="Tower A")
    signage_a = Signage(code="SIGN-A", name="Signage A")
    signage_b = Signage(code="SIGN-B", name="Signage B")
    db_session.add_all([destination, signage_a, signage_b])
    db_session.flush()

    db_session.add_all(
        [
            SignageRoute(signage_id=signage_a.id, destination_id=destination.id, direction="right"),
            SignageRoute(
                signage_id=signage_b.id, destination_id=destination.id, direction="straight"
            ),
        ]
    )
    db_session.commit()

    route_a = resolve_signage_route(db_session, signage_a.id, destination.id)
    route_b = resolve_signage_route(db_session, signage_b.id, destination.id)

    assert route_a.direction == "right"
    assert route_b.direction == "straight"
    assert build_display_message(route_a, destination) == "Tower A - right"
    assert build_display_message(route_b, destination) == "Tower A - straight"


def test_build_display_message_uses_custom_label_when_set(db_session: Session) -> None:
    destination = Destination(name="Lot A")
    signage = Signage(code="SIGN-01", name="Entrance")
    db_session.add_all([destination, signage])
    db_session.flush()

    route = SignageRoute(
        signage_id=signage.id,
        destination_id=destination.id,
        direction="left",
        display_label="Visitor parking, past the barrier",
    )
    db_session.add(route)
    db_session.commit()

    assert build_display_message(route, destination) == "Visitor parking, past the barrier"


def test_build_display_message_fallback_when_no_route() -> None:
    destination = Destination(name="Lot A")
    assert build_display_message(None, destination) == UNROUTED_MESSAGE


def test_unique_constraint_one_route_per_signage_destination_pair(
    db_session: Session, sample_setup: dict
) -> None:
    db_session.add(
        SignageRoute(
            signage_id=sample_setup["signage"].id,
            destination_id=sample_setup["destination"].id,
            direction="left",
        )
    )
    db_session.commit()

    db_session.add(
        SignageRoute(
            signage_id=sample_setup["signage"].id,
            destination_id=sample_setup["destination"].id,
            direction="right",
        )
    )
    with __import__("pytest").raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_routing_table_page_shows_configured_and_unconfigured(
    client, db_session: Session, sample_setup: dict
) -> None:
    response = client.get(f"/signages/{sample_setup['signage'].id}/routes")
    assert response.status_code == 200
    assert "Not configured" in response.text
    assert "Lot A" in response.text


def test_save_signage_route_via_admin_form(
    client, db_session: Session, sample_setup: dict
) -> None:
    signage = sample_setup["signage"]
    destination = sample_setup["destination"]

    response = client.post(
        f"/signages/{signage.id}/routes",
        data={
            "destination_id": destination.id,
            "direction": "right",
            "display_label": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    route = db_session.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage.id, SignageRoute.destination_id == destination.id
        )
    )
    assert route is not None
    assert route.direction == "right"


def test_bulk_update_signage_routes_moves_destinations_between_buckets(
    client, db_session: Session, sample_setup: dict
) -> None:
    """Improvement 2: the batch endpoint used by the bucket drag-and-drop UI."""
    signage = sample_setup["signage"]
    destination = sample_setup["destination"]
    other_destination = Destination(name="Lot Z")
    db_session.add(other_destination)
    db_session.flush()
    db_session.add_all(
        [
            SignageRoute(signage_id=signage.id, destination_id=destination.id, direction="unset"),
            SignageRoute(
                signage_id=signage.id, destination_id=other_destination.id, direction="unset"
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        f"/signages/{signage.id}/routes/bulk-update",
        json={str(destination.id): "left", str(other_destination.id): "right"},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 2

    route = db_session.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage.id, SignageRoute.destination_id == destination.id
        )
    )
    other_route = db_session.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage.id,
            SignageRoute.destination_id == other_destination.id,
        )
    )
    assert route.direction == "left"
    assert other_route.direction == "right"


def test_ensure_signage_routes_backfills_all_destinations(db_session: Session) -> None:
    """Improvement 2: a new signage immediately gets an "unset" route for
    every EXISTING destination (services.ensure_signage_routes)."""
    from app.services import ensure_signage_routes

    destination_a = Destination(name="Lot A")
    destination_b = Destination(name="Lot B")
    db_session.add_all([destination_a, destination_b])
    db_session.flush()

    signage = Signage(code="SIGN-NEW", name="New signage")
    db_session.add(signage)
    db_session.flush()

    created = ensure_signage_routes(db_session, signage)
    db_session.commit()

    assert created == 2
    routes = list(
        db_session.scalars(select(SignageRoute).where(SignageRoute.signage_id == signage.id))
    )
    assert {r.destination_id for r in routes} == {destination_a.id, destination_b.id}
    assert all(r.direction == "unset" for r in routes)


def test_ensure_destination_routes_backfills_all_signages(db_session: Session) -> None:
    """The mirror case: a new destination gets an "unset" route on every
    EXISTING signage (services.ensure_destination_routes)."""
    from app.services import ensure_destination_routes

    signage_a = Signage(code="SIGN-A", name="Signage A")
    signage_b = Signage(code="SIGN-B", name="Signage B")
    db_session.add_all([signage_a, signage_b])
    db_session.flush()

    destination = Destination(name="Lot New")
    db_session.add(destination)
    db_session.flush()

    created = ensure_destination_routes(db_session, destination)
    db_session.commit()

    assert created == 2
    routes = list(
        db_session.scalars(select(SignageRoute).where(SignageRoute.destination_id == destination.id))
    )
    assert {r.signage_id for r in routes} == {signage_a.id, signage_b.id}
    assert all(r.direction == "unset" for r in routes)


def test_backfill_all_signage_routes_fills_in_missing_pairs(db_session: Session) -> None:
    """services.backfill_all_signage_routes: the startup migration step that
    creates any (signage, destination) row missing across the whole database."""
    from app.services import backfill_all_signage_routes

    destination_a = Destination(name="Lot A")
    destination_b = Destination(name="Lot B")
    signage = Signage(code="SIGN-01", name="Entrance")
    db_session.add_all([destination_a, destination_b, signage])
    db_session.commit()

    # No signage_routes rows exist yet - this simulates data from before the
    # feature existed (or created by the ORM without the ensure_* helpers).
    assert db_session.scalar(select(SignageRoute)) is None

    created = backfill_all_signage_routes(db_session)
    assert created == 2

    routes = list(db_session.scalars(select(SignageRoute)))
    assert len(routes) == 2
    assert all(r.direction == "unset" for r in routes)

    # Safe to run again: nothing new is created the second time.
    assert backfill_all_signage_routes(db_session) == 0


def test_create_signage_via_admin_form_backfills_routes(
    client, db_session: Session, sample_setup: dict
) -> None:
    """The admin "add signage" form auto-creates the base pairing too."""
    response = client.post(
        "/signages",
        data={"code": "SIGN-NEW", "name": "New signage"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    signage = db_session.scalar(select(Signage).where(Signage.code == "SIGN-NEW"))
    assert signage is not None
    route = db_session.scalar(
        select(SignageRoute).where(
            SignageRoute.signage_id == signage.id,
            SignageRoute.destination_id == sample_setup["destination"].id,
        )
    )
    assert route is not None
    assert route.direction == "unset"


def test_create_destination_via_admin_form_backfills_routes(
    client, db_session: Session, sample_setup: dict
) -> None:
    """The admin "add destination" form auto-creates the base pairing too."""
    response = client.post(
        "/destinations", data={"name": "Lot New"}, follow_redirects=False
    )
    assert response.status_code == 303

    destination = db_session.scalar(select(Destination).where(Destination.name == "Lot New"))
    assert destination is not None
    route = db_session.scalar(
        select(SignageRoute).where(
            SignageRoute.destination_id == destination.id,
            SignageRoute.signage_id == sample_setup["signage"].id,
        )
    )
    assert route is not None
    assert route.direction == "unset"
