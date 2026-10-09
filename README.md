# Ghost Controller

Production-grade **native** ground control station (no web-view wrapper) for
**Linux first, then Windows**, built with **PySide6 + Qt Quick (QML)** — the
same toolkit QGroundControl uses — running the proven backend worker stack
**in-process**, self-contained in this repository.

The UI is a faithful native port of the proven **web-gcs** HUD (same layout,
colors and interactions); the backend is the same MAVLink worker stack the
web GCS serves over REST, minus FastAPI/websockets — and minus the AI
assistant / vehicle-detection (vision) modules, which are intentionally NOT
part of the desktop build.

```
┌─────────────────────────────────────────────────────┐
│  ghost-handler (native binary)                      │
│                                                     │
│  QML video-first HUD             Python bridge      │
│  ├─ FlightView (video/horizon +  ◄─────  Telemetry   │
│  │   tapes, ladder, actions)            Vehicle      │
│  ├─ MapScreen (offline tiles +          Mission      │
│   │   FLIGHT DATA panel)                Video        │
│  ├─ MissionPlanner (waypoints,          MapBridge    │
│   │   fence, survey, orbit tools)                    │
│  └─ VideoSource + GCS menu drawers                   │
│                          │                           │
│            app/bridge/backend.py                     │
│    SimulatedSource (--sim) │ BackendRuntimeSource    │
│    DisconnectedSource ─────┘ imports backend/        │
│                          (vendored, self-contained)  │
│                          mavlink.shared_state        │
╔═════════════════════════════════════════════════════╗
```

## Connection honesty (read this first)

The HUD **never pretends a vehicle is connected**:

* `python main.py` → the VENDORED backend (this repo's `backend/mavlink`)
  starts in-process and listens on the configured MAVLink transport.
  (`backend/gcs.env` or `MAVLINK_CONNECTION`; default
  `udpin:127.0.0.1:14550`). The HUD stays DISCONNECTED — with the listening
  address shown — until a real vehicle heartbeat arrives.
* `GH_BACKEND_PATH=/path/to/backend` points at an external backend checkout
  for A/B debugging; `GH_BACKEND_PATH=none` disables the backend entirely.
* `python main.py --sim` (or `GH_SIM=1`) → the simulated flight, and the
  TopBar brand reads **GCS · SIM** so a demo can never be mistaken for a live
  vehicle (explicit `--sim` wins).

## Run (development)

```bash
python3 -m venv .venv-desktop
.venv-desktop/bin/pip install -r requirements.txt
.venv-desktop/bin/python tools/gen_tokens.py   # tokens.json → Token.qml
.venv-desktop/bin/python main.py               # honest NO LINK (no vehicle)
.venv-desktop/bin/python main.py --sim         # simulated flight for demos
tools/run_desktop.sh                           # same, with env helpers
```

Dependencies (`requirements.txt`): `PySide6-Essentials`, `numpy`,
`av` (RTP/H.264 decode), `opencv-python-headless` (rtsp/mjpeg/webcam),
`pymavlink`, `pyserial`. **No openai, no ultralytics** — AI/vision are not
part of the desktop build.

## UI (web-gcs parity)

The shell is the web HUD, ported element-for-element under a persistent
TopBar (`GCS ▾ · MODE ▾ · GPS ▾ · BATT ····· FIRMWARE · [ARMED]`):

* **TopBar** — logo opens the GCS menu (Mission Uploader / Video Source);
  ModeSelector dropdown grouped MANUAL/ASSISTED/AUTO/ADVANCED with modes per
  detected firmware (PX4/ArduPilot); GpsIndicator with satellite bars + click
  popup (FIX/HDoP/VDoP/COG/lat/lon/alt); battery icon + volts; firmware badge
  (PX4 blue / ArduPilot green); ARMED/DISARMED pill.
* **FlightView** — full-bleed video (or gradient horizon when no stream),
  heading readout + roll arc, pitch ladder, crosshair with wing chevrons,
  SPEED (left edge) / ALT (right edge) tapes with tick columns, action
  cluster (ARM/DISARM · TAKEOFF · LAND · RTL · START MISSION · KILL SWITCH
  double-click), YAW/PITCH/CLIMB chips, corner brackets. The web's
  COG-while-moving / yaw-when-slow heading policy is replicated in the
  bridge.
* **MapScreen** — expanded map (round button on the flight view) with the
  FLIGHT DATA panel, MAP HUD pill, OFFLINE/MAP ✓ upload button + image-overlay
  config (SW/NE corners like the web MapUploadPanel), compass rose, collapse
  button back to flight.
* **MissionPlanner** — click-to-add waypoints (TAKEOFF gold, WAYPOINT blue,
  LAND red), draw fence (cyan dashed polygon + numbered vertices), delete
  tools, per-waypoint editor (COMMAND/ALTITUDE), survey grid generator
  (width/height/spacing/angle/altitude — identical boustrophedon math to the
  web), LIVE ORBIT tool (click map → `ORBIT` through the proven command
  stack), import/export JSON **and QGC `.waypoints`**, upload/download/clear
  mission + fence to the vehicle (mission_safety validation applies).
* **VideoSourcePanel** (GCS menu → Video Source) — AUTO (listens on RTP
  5600; NO SIGNAL until a stream starts — never a fake test pattern),
  RTP 5600, RTSP, MJPEG with custom-URL editors, feedback line; persists via
  QSettings like the web persists to gcs.env.
* **Alerts** — top-center banner strip (danger red / warn amber), 4 s
  low-priority auto-clear, click to dismiss.

## Video

* **auto / udp_rtp** — PX4 SITL / drone H.264 RTP over UDP (QGC convention
  port 5600), decoded natively via a synthetic SDP + PyAV (no GStreamer).
  `GH_VIDEO_RTP_PORT` overrides the port.
* **rtsp / mjpeg** — OpenCV/stdlib capture, retried forever until stopped (a
  dead camera never kills the worker thread). Custom URLs are probed first,
  exactly like the backend's source_detector.
* **test** — synthetic pattern, CI/demo only (tests, or
  `GH_VIDEO_ALLOW_INTERNAL_MODES=1`; not shown in the UI panel).

Dependencies (Python 3.10 venv): `numpy`, `av==12.3.0`,
`opencv-python-headless`. On Python ≥3.11 prefer `av==13.1.1`.

## Offline basemap + online fallback

Basemap priority (web SmartTileLayer parity):

1. **Custom image overlay** — operator-uploaded image + SW/NE geographic
   corners (persisted via QSettings).
2. **Offline tiles** — `maps/` is auto-detected (`GH_MAP_SOURCE` overrides):
   an XYZ dir, `.pmtiles`/`.mbtiles` file all work; a small real OSM basemap
   around the PX4 SITL home (Zurich) ships via:
   ```bash
   tools/fetch_osm_tiles.sh   # resumable; polite (OSM tile policy)
   ```
3. **Online OSM** — `tile.openstreetmap.org` with a disk cache
   (`~/.cache/ghost-handler/osm-tiles`), so a pre-flown area keeps rendering
   offline in the field. Polite default UA (`GH_MAP_USER_AGENT` overrides);
   cache pre-warming for planned missions is future work (see
   `app/map/osm.py`).

Zoom clamps to the source's real coverage; when NO basemap can paint (no
offline tiles AND OSM offline) the map shows the flat grid fallback.

## PX4 SITL end-to-end

```bash
.venv-desktop/bin/python tests/sitl_e2e_test.py            # connect + telemetry + video
GH_SITL_FLY=1 .venv-desktop/bin/python tests/sitl_e2e_test.py   # + arm/takeoff/land
tests/sitl_e2e_test.py --cleanup                           # remove PX4 tree additions
```

## Verify

```bash
.venv-desktop/bin/python tests/smoke_test.py              # headless boot → build/smoke.png
GH_SMOKE_VIEW=map|planner .venv-desktop/bin/python main.py --smoke  # other views
GH_SMOKE_VIDEO=1 .venv-desktop/bin/python main.py --smoke # + video panel in the grab
.venv-desktop/bin/python tests/test_tiles.py              # offline tile readers (PMTiles spec vectors)
.venv-desktop/bin/python tests/test_video.py              # video pipeline incl. real RTP/H.264 via ffmpeg
.venv-desktop/bin/python tests/test_backend_runtime.py    # vendored backend in-process (MAVLink round-trips)
.venv-desktop/bin/python tools/record_demo.py             # MP4 walkthrough + stills
```

Tests set `GH_QSETTINGS_APP=ghost-handler-tests` so they never write the
operator's real QSettings (org/app `"Ghost Handler"`).

## Build native binary (Linux)

```bash
./packaging/build-linux.sh             # dist/ghost-handler/ghost-handler
./packaging/build-linux.sh --appimage  # + distributable .AppImage
```

Windows installer ships after Linux parity (PyInstaller + Inno Setup).

## Design system / Figma

- `design/tokens.json` — single source of truth (colors, spacing, type, motion)
- `tools/gen_tokens.py` — emits `qml/theme/Token.qml` (the web CSS/Tailwind
  outputs were removed with the web parity port)

## Conventions

- QML files never compute vehicle logic — presentation only; logic lives in the bridge.
- All UI values come from `Token` (generated) — no magic colors/sizes in QML (the web-parity hex values live in tokens.json).
- The app never fabricates state: no simulated telemetry without `--sim`, no
  synthetic video without explicitly selecting the test source, no optimistic
  link status before a real heartbeat.
- AI (NLP assistant + confirm-to-fly) and vehicle detection (YOLO vision)
  are **web-GCS features, not ported** — the desktop is a pure flight ops
  tool.
