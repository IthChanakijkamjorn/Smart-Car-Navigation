# Smart Car Navigation

An **on-premise** parking guidance system: a Dahua LPR camera reads a car's
license plate at the gate, this server looks the plate up, and the MAXHUB
signage in front of the driver immediately shows where to go
(e.g. `← Lot A`).

Everything runs on **one small computer (mini PC / NUC) on the customer's local
network**. There is no cloud, no domain name and no internet dependency. If the
site's internet connection dies, the system keeps working.

---

## 1. How the pieces fit together

```
 [Dahua LPR camera] ──HTTP POST /api/detections──┐
                                                 ▼
                            ┌──────────────────────────────────────┐
                            │  Mini PC on the local network        │
                            │  ─ this application (FastAPI)        │
                            │  ─ SQLite database file              │
                            └──────────────────────────────────────┘
                                 ▲                        ▲
        guard's browser ─────────┘                        └───── MAXHUB screen's
   http://<server-ip>:8000/                                      browser, kiosk mode
   (dashboard, CSV import, logs)                          http://<server-ip>:8000/signage/SIGN-01
                                                          (polls once per second)
```

**You do not install any code on the camera or on the MAXHUB screen.** They are
just network devices:

* the camera is *configured* (in its own web interface) to POST its detections
  to this server,
* the screen simply *opens a web page* served by this server in full-screen
  (kiosk) mode. No app installation, no app store — just a URL.

One backend application exposes three interfaces:

| Interface | URL | Audience |
| --- | --- | --- |
| Detection webhook | `POST /api/detections` | Dahua cameras (machine to machine) |
| Admin / guard dashboard | `/` (Map View), `/vehicles`, `/csv-import`, `/logs`, `/signages` | security guard / admin, in a browser |
| Signage routing table | `/signages/{id}/routes` | admin, configures per-signage direction |
| Map View upload/position | `/map/upload`, `/signages/{id}/position`, `/destinations/{id}/position` | admin, configures the Map View |
| Signage display | `/signage/{signage_code}` | the screen itself, no human interaction |
| Interactive API docs | `/docs` | you, while developing |

---

## 2. Tech stack

* **Python 3.11+ / FastAPI** — backend and HTML rendering
* **SQLite via SQLAlchemy ORM** — zero-administration local database. Because
  everything uses the ORM (no SQLite-specific SQL), switching to PostgreSQL
  later is only a change of the `DATABASE_URL` environment variable.
* **Jinja2 templates + a little vanilla JavaScript** — no frontend framework,
  no build step
* **uvicorn** — the ASGI web server
* **Docker / docker compose** — so the whole thing starts with one command on
  the customer's mini PC

---

## 3. Running it

### Option A — Docker (recommended on the customer's mini PC)

```bash
docker compose up --build
```

Then open `http://<server-ip>:8000/`. The database file lives in the named
volume `db_data`, so data survives restarts and image rebuilds.

### Option B — plain Python (recommended while developing)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/seed_data.py        # optional: create sample data
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`--host 0.0.0.0` is important: it makes the server reachable from the cameras
and the signage screens, not only from the mini PC itself.

### Create sample data

```bash
python scripts/seed_data.py            # or: curl -X POST http://127.0.0.1:8000/api/seed
```

This creates destinations `Lot A/B/C`, two signages (`SIGN-01`, `SIGN-02`) each
with their own camera, per-signage routing (see section 5a - e.g. `Lot A` is
"left" from `SIGN-01` but "straight" from `SIGN-02`) and two sample plates.

### Useful URLs

| URL | What it is |
| --- | --- |
| `http://<server-ip>:8000/` | dashboard overview |
| `http://<server-ip>:8000/vehicles` | registered plates + manual guard entry |
| `http://<server-ip>:8000/csv-import` | bulk CSV import |
| `http://<server-ip>:8000/logs` | detection event history |
| `http://<server-ip>:8000/signages` | manage screens, cameras, destinations |
| `http://<server-ip>:8000/signage/SIGN-01` | the display page for one screen |
| `http://<server-ip>:8000/docs` | auto-generated API documentation |
| `http://<server-ip>:8000/healthz` | health check |

---

## 4. Configuring a real Dahua LPR camera

1. Give the camera a **fixed IP** on the same LAN as the mini PC.
2. Open the camera's own web interface (`http://<camera-ip>`) and log in.
3. Enable the plate recognition / ANPR feature.
4. Find **Setting → Network → Alarm Server** (wording varies with firmware:
   "HTTP Push", "Event Push", "Alarm Center", "HTTP Listening"). Point it at:

   ```
   http://<server-ip>:8000/api/detections
   ```

   Method `POST`, content type `application/json`.
5. In the dashboard (`/signages`), add a **camera** whose *code* is exactly the
   camera ID the device sends (e.g. `CAM-ENTRANCE-01`) and link it to the
   signage that should react to it.

### Expected JSON payload

```json
{
  "plateNumber": "AB1234",
  "cameraID": "CAM-ENTRANCE-01",
  "timestamp": "2026-09-01T10:15:32Z",
  "confidence": 0.96,
  "snapshotBase64": "optional, currently logged only"
}
```

* Only `plateNumber` is required.
* `plate_number` / `camera_id` (snake_case) are accepted as well.
* Any **extra fields are kept** and stored verbatim in
  `detection_events.raw_payload`, so nothing is lost even if your firmware
  sends a different shape. If your camera's field names differ entirely, adjust
  the aliases in `app/schemas.py` (`DetectionIn`).

### What the server does with it

1. Writes the raw event to `detection_events` (permanent audit trail).
2. Normalises the plate (`ab-12 34` → `AB1234`) and looks it up in `vehicles`.
3. Resolves the destination for that plate.
4. Updates `signage_current_state` for the signage linked to that camera.
5. The signage page picks the change up on its next poll (≤ 1 second later).

If the plate is **not registered**, the screen shows the "unregistered" message
(`Please proceed to the guard booth` by default) so the guard can add the
vehicle manually from `/vehicles`.

---

## 5. Pointing a MAXHUB signage at the display page

The display is **just a web page** — you never install an app.

* **If the MAXHUB has a built-in browser (Android based):** open its browser,
  go to `http://<server-ip>:8000/signage/SIGN-01` and put the browser in
  full-screen / kiosk mode. Most models can auto-launch a URL at boot.
* **If the MAXHUB is used as a plain HDMI monitor:** attach a small device
  (Raspberry Pi / mini PC) and let its browser open the same URL in kiosk mode
  at boot, e.g.

  ```bash
  chromium-browser --kiosk --noerrdialogs --disable-infobars \
      http://192.168.1.50:8000/signage/SIGN-01
  ```

`SIGN-01` is the **signage code** you created on the `/signages` page — each
screen gets its own code and therefore its own URL, which is how a screen knows
"who am I".

The page refreshes itself every second via `GET /api/signage/{code}/current`.
It keeps showing the last message if the network hiccups and shows a small
`reconnecting…` indicator in the corner.

A message stays on screen for `DISPLAY_TTL_SECONDS` (15 by default) and then
falls back to the idle screen.

---

## 5a. Per-signage routing (direction depends on WHERE the signage is)

**Important design point:** `destinations` (e.g. "Tower A") no longer carries
a fixed direction. The correct direction depends on *which signage* is
showing it — a destination might be "turn right" from the signage at the
entrance and "go straight" from a second signage further down the road, even
though it's the exact same destination. This is modelled with a
`signage_routes` table: one row per `(signage, destination)` pair, holding
the `direction` (left/right/straight/u_turn, or any custom word) and an
optional custom `display_label` message.

To configure it:

1. Go to `/signages` and click **"Routing table"** next to a signage.
2. For each destination, pick a direction (and, optionally, type a custom
   message instead of the default "`<destination>` - `<direction>`" text).
3. Repeat for every other signage — the same destination can have a totally
   different direction configured there.

**What happens if a signage was never configured for a destination?** The
screen falls back to a safe message (`See attendant` by default, configurable
via `UNROUTED_MESSAGE`) instead of guessing a direction, and a warning is
logged server-side so you notice the gap. This shows up as `"state": "unrouted"`
on the polling API.

---

## 5b. Dashboard Map View

The dashboard landing page (`/`) shows a **Map View**: your uploaded site map
image with clickable pins for every signage and destination that has a map
position set.

* **Upload the map image:** go to `/map/upload` and upload a PNG/JPG/GIF/WEBP
  (max 8 MB) — a photo, floor plan or scanned drawing of the site. It is
  stored under `app/static/uploads/` and remembered in the single-row
  `map_settings` table.
* **Set a marker's position:** on `/signages`, each signage/destination has a
  **"Map position"** link — a simple form where you type X/Y as percentages
  (0-100) of the image's width/height (e.g. "50, 50" is the dead centre).
  Leave both blank to remove the marker.
* **Using the map:** click 🖥️ (signage) or 📍 (destination) markers to open a
  details panel — for a signage this shows its location, what it is
  currently displaying (live, from `signage_current_state`), and links to its
  routing table and its position editor; for a destination it links to its
  position editor.
* **Possible future enhancement:** this iteration deliberately uses simple
  numeric inputs rather than drag-and-drop marker placement, to keep the
  implementation small. Drag-and-drop (dragging the pin directly on the map
  image and saving the resulting percentage) would be a nice usability
  upgrade later.

---

## 6. CSV import (pre-registered vehicles)

Go to `/csv-import` and upload a UTF-8 CSV with a header row:

```csv
plate_number,destination_name,notes
AB1234,Lot A,Resident tower 1
XY9999,Lot B,Monthly tenant
```

* `plate_number` — **required**; spaces, dashes and dots are ignored when
  matching (`EF-2020` and `ef 2020` are the same car).
* `destination_name` — **required**; a destination that does not exist yet is
  created automatically (just the name — direction is configured separately,
  per signage; see section 5a below).
* `notes` — optional.

A plate that already exists is **updated**, not duplicated. Rows with missing
data are skipped and reported back on the result page. Maximum file size: 1 MB.

A ready-made example lives in [`sample_data/vehicles_sample.csv`](sample_data/vehicles_sample.csv).

Unregistered visitors are handled the other way around: the guard types the
plate and destination into the form on `/vehicles`.

---

## 7. Testing without any hardware

Start the server, then in another terminal:

```bash
python scripts/simulate_camera_event.py                      # plate AB1234, CAM-ENTRANCE-01
python scripts/simulate_camera_event.py --plate XY9999
python scripts/simulate_camera_event.py --url http://192.168.1.50:8000 --plate ZZ0000
```

Keep `http://127.0.0.1:8000/signage/SIGN-01` open in a browser while you run it
and watch the screen change, then return to idle after 15 seconds.

Run the unit tests with:

```bash
pytest
```

They cover plate lookup/matching, CSV import parsing and the detection endpoint
updating `signage_current_state`.

---

## 8. Configuration

Set these as environment variables (or in `docker-compose.yml`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/smart_car_navigation.db` | Database location. Use a PostgreSQL URL to migrate later. |
| `DISPLAY_TTL_SECONDS` | `15` | How long a message stays on a screen before idle. |
| `UNREGISTERED_MESSAGE` | `Please proceed to the guard booth` | Shown when a plate is unknown. |
| `UNROUTED_MESSAGE` | `See attendant` | Shown when the destination is known but this signage has no route configured for it. |

---

## 9. Project layout

```
app/
  main.py             FastAPI app, startup, /healthz, /api/seed
  database.py         SQLAlchemy engine/session + init_db()
  models.py           vehicles, destinations, signages, cameras,
                      signage_routes, map_settings, detection_events,
                      signage_current_state
  schemas.py          JSON request/response shapes
  services.py         business logic (plate matching, detections,
                      per-signage route resolution, CSV import)
  seed.py             sample data
  templating.py       shared Jinja2 environment
  routers/
    detections.py     POST /api/detections  (camera webhook)
    admin.py          dashboard/Map View landing page, vehicles, CSV, logs,
                      signages/cameras/destinations management
    map_admin.py      signage routing tables, map image upload, marker positions
    signage.py        /signage/{code} + /api/signage/{code}/current
  templates/
    dashboard/        base.html, index.html (Map View), vehicles.html,
                      csv_import.html, logs.html, signages.html, routes.html,
                      map_upload.html, position.html
    signage/          display.html
  static/             dashboard.css, signage.css, signage.js
  static/uploads/     uploaded site map images (not committed - see .gitignore)
scripts/
  seed_data.py               create sample data from the command line
  simulate_camera_event.py   fake a camera detection for local testing
sample_data/
  vehicles_sample.csv        example import file
tests/                       pytest suite
```

---

## 10. Known gaps / next steps

These were intentionally left out of this first scaffold:

* **No authentication yet.** Anyone on the LAN can open the dashboard and the
  webhook. **Add simple session-based login for the admin dashboard (and a
  shared-secret header or firewall rule for `/api/detections`) before the system
  is used for real.** Also remove or protect `POST /api/seed`.
* **No Alembic migrations yet.** Tables are created by `init_db()` at startup,
  which is fine while the schema is new. Once the system is live and holds real
  data, add Alembic (`alembic init alembic`, point `sqlalchemy.url` at
  `DATABASE_URL`, `alembic revision --autogenerate`) and stop calling
  `init_db()` so schema changes never risk the data.
* **Polling, not push.** The signage polls once per second, which is more than
  fast enough for a car driving towards the gate and is far simpler to debug.
  MQTT or WebSockets can be added later for sub-second latency **without any
  database change** — the delivery mechanism is the only thing that differs.
* **No occupancy / capacity based redirection.** The mapping is a static
  plate → destination. The `destinations` table is deliberately free of
  constraints that would block adding `capacity` / `current_occupancy` columns
  later.
* **No drag-and-drop marker placement on the Map View.** Positions are set via
  a simple numeric (percentage) form for now - see section 5b. Drag-and-drop
  would be a nice future enhancement.
* **Snapshots are not stored as files.** The base64 image sent by the camera is
  kept inside the raw payload only.
* **No HTTPS.** Not required on an isolated LAN, but worth adding if the network
  is shared.
