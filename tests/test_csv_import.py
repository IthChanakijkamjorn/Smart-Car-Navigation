"""Tests for CSV parsing and import."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Destination, Vehicle
from app.services import import_vehicles_csv, parse_vehicles_csv

SAMPLE_CSV = Path(__file__).resolve().parents[1] / "sample_data" / "vehicles_sample.csv"


def test_parse_vehicles_csv_normalises_and_reports_errors() -> None:
    rows, errors = parse_vehicles_csv(
        "Plate Number,destination_name,notes\n"
        "ab-1234,Lot A,resident\n"
        ",Lot B,missing plate\n"
        "CD5678,,missing destination\n"
        "\n"
    )

    assert rows == [
        {"plate_number": "AB1234", "destination_name": "Lot A", "notes": "resident"}
    ]
    assert len(errors) == 2
    assert "missing plate_number" in errors[0]


def test_parse_empty_csv() -> None:
    rows, errors = parse_vehicles_csv("")
    assert rows == []
    assert errors == ["The CSV file is empty or has no header row."]


def test_parse_sample_file() -> None:
    rows, errors = parse_vehicles_csv(SAMPLE_CSV.read_text(encoding="utf-8"))
    assert errors == []
    assert {row["plate_number"] for row in rows} >= {"AB1234", "EF2020", "GH4141"}


def test_import_creates_destinations_and_updates_existing(db_session: Session) -> None:
    result = import_vehicles_csv(db_session, "plate_number,destination_name\nAB1234,Lot A\n")
    assert (result.created, result.updated) == (1, 0)
    assert db_session.scalar(select(Destination).where(Destination.name == "Lot A")) is not None

    # Re-importing the same plate with a new destination updates it in place.
    result = import_vehicles_csv(db_session, "plate_number,destination_name\nab 1234,Lot B\n")
    assert (result.created, result.updated) == (0, 1)

    vehicles = list(db_session.scalars(select(Vehicle)))
    assert len(vehicles) == 1
    assert vehicles[0].destination.name == "Lot B"


def test_csv_import_endpoint(client, db_session: Session) -> None:
    response = client.post(
        "/csv-import",
        files={"file": ("vehicles.csv", SAMPLE_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200
    assert db_session.scalar(select(Vehicle).where(Vehicle.plate_number == "GH4141")) is not None
