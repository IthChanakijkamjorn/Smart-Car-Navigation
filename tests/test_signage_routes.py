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
    assert "not configured" in response.text


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


def test_delete_signage_route(client, db_session: Session, sample_setup: dict) -> None:
    signage = sample_setup["signage"]
    destination = sample_setup["destination"]
    db_session.add(
        SignageRoute(signage_id=signage.id, destination_id=destination.id, direction="left")
    )
    db_session.commit()

    response = client.post(
        f"/signages/{signage.id}/routes/{destination.id}/delete", follow_redirects=False
    )
    assert response.status_code == 303
    assert db_session.scalar(select(SignageRoute)) is None
