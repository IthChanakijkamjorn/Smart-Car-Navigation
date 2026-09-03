#!/usr/bin/env python3
"""Send a fake Dahua plate detection to the server - no hardware needed.

Examples::

    # default: plate AB1234 from CAM-ENTRANCE-01 on the local machine
    python scripts/simulate_camera_event.py

    # a specific plate / camera / server
    python scripts/simulate_camera_event.py --plate XY9999 --camera CAM-ENTRANCE-01
    python scripts/simulate_camera_event.py --url http://192.168.1.50:8000

Then watch http://<server>/signage/SIGN-01 change for a few seconds.

Only the Python standard library is used so this runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def build_payload(plate: str, camera: str, confidence: float) -> dict[str, object]:
    """Build a payload shaped like a Dahua "Alarm Server" HTTP push."""
    return {
        "plateNumber": plate,
        "cameraID": camera,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": confidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of the server")
    parser.add_argument("--plate", default="AB1234", help="Plate number to simulate")
    parser.add_argument("--camera", default="CAM-ENTRANCE-01", help="Camera code")
    parser.add_argument("--confidence", type=float, default=0.96, help="Confidence 0-1")
    args = parser.parse_args()

    endpoint = args.url.rstrip("/") + "/api/detections"
    payload = build_payload(args.plate, args.camera, args.confidence)
    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )

    print(f"POST {endpoint}\n{json.dumps(payload, indent=2)}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(f"\nHTTP {response.status}")
            print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"\nCould not reach {endpoint}: {exc.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
