#!/usr/bin/env python3
"""Create sample destinations / signages / cameras / vehicles.

Usage (from the repository root)::

    python scripts/seed_data.py

The same thing can be done over HTTP with ``POST /api/seed``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this file directly, without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db  # noqa: E402
from app.seed import seed  # noqa: E402


def main() -> int:
    init_db()
    with SessionLocal() as db:
        created = seed(db)
    print("Sample data created:", created)
    print("Open http://127.0.0.1:8000/ for the dashboard.")
    print("Open http://127.0.0.1:8000/signage/SIGN-01 for the signage display.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
