# Frontend (UI) file map — for design/development handoff

All UI is **QML** (Qt Quick) under `qml/`. It is presentation-only: it reads
context properties exposed by Python (`Telemetry`, `Vehicle`, `Mission`,
`Video`, `MapBridge`, `AppInfo`, `DataLake`) and calls their Slots for
actions. No business logic lives in QML.

## Shell & chrome
| File | Role |
|---|---|
| `qml/Main.qml` | App shell: view stack (`flight` / `map` / `planner`), video drawer, alert banner, `viewMode`/`videoOpen` properties |
| `qml/views/TopBar.qml` | Logo + GCS menu, mode selector, GPS, battery, firmware, ARM pill |
| `qml/views/ModeSelector.qml` | Flight-mode dropdown (grouped MANUAL/ASSISTED/AUTO/ADVANCED; TAKEOFF sequence) |
| `qml/views/GpsIndicator.qml` | Satellite bars + GPS status popup (fix/hdop/vdop/cog) |

## Views
| File | Role |
|---|---|
| `qml/views/FlightView.qml` | Video-first HUD: video/horizon, SPEED/ALT tapes, pitch ladder, crosshair, YAW/PITCH/CLIMB chips, command cluster, link/camera/signal overlays |
| `qml/views/MapScreen.qml` | Expanded map + FLIGHT DATA panel + offline map upload panel |
| `qml/views/MissionPlanner.qml` | Full-screen planner: waypoints, fence, survey, orbit, QGC import |
| `qml/views/MapView.qml` | Slippy-map engine (tiles, pan/zoom, markers, follow, track/fence/mission lines) — shared by MapScreen & MissionPlanner |
| `qml/views/VideoSourcePanel.qml` | Video source drawer: AUTO / RTP / RTSP / MJPEG rows + custom URLs |

## Reusable components
`qml/components/` — AlertBanner (click-to-dismiss), EdgeTape, RollArc,
PitchLadder, Compass, BatteryIcon, SignalBars, HudCmdButton, GlassPanel,
PlannerDropdown, PlannerToolButton, LabeledNumber, HorizontalHairline,
SegControl, PanelTitle, Icon (SF Symbols-style line icons on a 24px grid —
add new ones to its `paths` map; write SVG arc flags spaced out, Qt rejects
the packed `0 110 11` form), SoftShadow (shader-free drop shadow — use it instead
of MultiEffect so panels still render on the software Qt Quick backend).

## Design tokens & themes
- Light/dark: `tokens.json` holds the dark palette; `themes.light` overrides
  colours. `gen_tokens.py` turns overridden tokens into bindings on
  `Token.theme`, so the whole UI restyles live. `app/bridge/theme.py`
  (`Theme` in QML: `preference`, `setPreference("dark"|"light"|"system")`)
  owns the saved choice. Never hardcode `#FFFFFF` for panel text — use
  `Token.color_ui_text`; keep white only for on-video HUD marks
  (`Token.color_hud_text`) and labels on tinted buttons (`Token.color_ui_onTint`).
  Smoke a theme without saving it: `GH_THEME=light`.
- HUD ink: anything drawn over live video uses `Token.hudInk` /
  `Token.hudInkShadow` (writable, set by `Theme.setHudColor("#RRGGBB")` from
  the menu swatches; presets in `HUD_PRESETS`, app/bridge/theme.py). Canvases
  must expose `property color ink: Token.hudInk` and repaint `onInkChanged`.
- `design/tokens.json` — single source of truth (colors, typography, spacing)
- `qml/theme/Token.qml` — generated from it (do **not** hand-edit;
  regenerate: `.venv-desktop/bin/python tools/gen_tokens.py`)
- UI font: Inter (`assets/fonts/Inter-*.ttf`, OFL — the open SF Pro stand-in),
  set app-wide in `app/application.py`; live numeric readouts add
  `font.features: { "tnum": 1 }` for tabular digits
- `assets/Logo.jpg` (light), `assets/Logo-mark.png` (white mark for the dark chrome), `assets/icons.svg`

## Python seams the UI binds to (read-only reference for the dev)
| Context property | File |
|---|---|
| `Telemetry` | `app/bridge/telemetry.py` (frame fields, alerts, positionTrack) |
| `Vehicle` | `app/bridge/vehicle.py` (modes table, preflight/health, commands) |
| `Mission` | `app/bridge/mission.py` (waypoints, fence, survey, orbit) |
| `Video` | `app/video/controller.py` (state/label/fps/frameSeq, setMode) |
| `MapBridge` | `app/bridge/mapbridge.py` (tiles, overlay, status) |

## Conventions / gotchas
- `Window.window.viewMode = "map"` switches views; every file touching
  `Window.` needs `import QtQuick.Window`.
- LabeledNumber takes **string** values; `parseFloat()` at call sites.
- Canvas items need explicit `var ctx = getContext("2d")` in `onPaint`.
- Smoke-check any QML edit headless:
  `GH_SMOKE_VIEW=flight .venv-desktop/bin/python main.py --smoke`
  (also `map`, `planner`, and `GH_SMOKE_VIDEO=1`) — grabs `build/smoke.png`.
