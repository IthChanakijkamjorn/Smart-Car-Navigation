"""Tests for plate normalisation and lookup."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import Vehicle, VehicleSource
from app.services import find_vehicle_by_plate, normalize_plate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ab1234", "AB1234"),
        (" AB 1234 ", "AB1234"),
        ("ab-12.34", "AB1234"),
        ("", ""),
    ],
)
def test_normalize_plate(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


def test_find_vehicle_by_plate_ignores_formatting(
    db_session: Session, sample_setup: dict
) -> None:
    db_session.add(
        Vehicle(
            plate_number="AB1234",
            destination_id=sample_setup["destination"].id,
            source=VehicleSource.CSV_IMPORT,
        )
    )
    db_session.commit()

    assert find_vehicle_by_plate(db_session, "ab 1234") is not None
    assert find_vehicle_by_plate(db_session, "AB-1234").destination.name == "Lot A"


def test_find_vehicle_by_plate_returns_none_for_unknown(db_session: Session) -> None:
    assert find_vehicle_by_plate(db_session, "ZZ0000") is None
    assert find_vehicle_by_plate(db_session, "   ") is None
