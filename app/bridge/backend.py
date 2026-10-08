"""Telemetry sources.

`SimulatedSource` — 10 Hz synthetic flight for UI development (M1).
`BackendRuntimeSource` — consumes the PROVEN backend worker stack running
in-process (see app/backend/runtime.py), draining the telemetry mirror queue
that `backend/mavlink/telemetry_worker.py` fills via its `out_queue` kwarg.

Frame contract (dict, all values JSON-native):
    connected, armed, mode, state, speed, altitude, climb, heading,
    roll, pitch, lat, lon, battery_pct, battery_v, gps_fix, sats, rssi,
    cog, hdop, vdop, gps_vel, ready, health_reason, health_message
    plus `extra`: raw sub-dicts (battery/gps_raw/signal/velocity) for panels.

The web GCS derives its heading from GPS COG while actually moving and falls
back to attitude yaw when slow (getSpeed.ts COG_MIN_SPEED_MS = 0.5); that
policy is replicated here so the desktop HUD heading matches the web HUD.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from queue import Empty

COG_MIN_SPEED_MS = 0.5  # below this, GPS COG is noise (web getSpeed.ts)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class SimulatedSource:
    """Synthetic flight generator. `poll()` advances the internal clock."""

    name = "simulated"

    def __init__(self) -> None:
        self._t = 0.0

    def poll(self) -> dict:
        self._t += 0.1
        t = self._t
        flying = t > 4.0
        mode = "STANDBY" if t < 4.0 else ("TAKEOFF" if t < 9.0 else "AUTO")
        connected = t > 1.0
        prev_alt = max(0.0, 25.0 * (self._t - 0.1 - 4.0) / 5.0) if self._t < 9.1 else (
            25.0 + 4.0 * math.sin(0.25 * (self._t - 0.1)))
        alt = max(0.0, 25.0 * (t - 4.0) / 5.0) if t < 9.0 else (25.0 + 4.0 * math.sin(0.25 * t))
        speed = (14.0 + 2.0 * math.sin(0.4 * t)) if flying else 0.0
        batt = _clamp(100.0 - 0.02 * t, 0.0, 100.0)
        cog = (t * 3.6) % 360.0
        return {
            "connected": connected,
            "armed": t > 3.0,
            "mode": mode,
            "state": "FLYING" if flying else ("CONNECTED" if connected else "DISCONNECTED"),
            "speed": round(speed, 2),
            "altitude": round(alt, 2),
            "climb": round((alt - prev_alt) / 0.1, 2) if t > 0.1 else 0.0,
            "heading": round(cog if speed >= COG_MIN_SPEED_MS else (t * 3.6) % 360.0, 1),
            "roll": round(6.0 * math.sin(0.5 * t), 1) if flying else 0.0,
            "pitch": round(3.0 * math.sin(0.33 * t), 1) if flying else 0.0,
            "lat": round(47.397742 + 0.0001 * math.sin(0.1 * t), 7),
            "lon": round(8.545594 + 0.0001 * math.cos(0.1 * t), 7),
            "battery_pct": round(batt, 1),
            "battery_v": round(25.2 - (100.0 - batt) * 0.02, 2),
            "gps_fix": 3 if t > 2.0 else 0,
            "sats": 14 + int(math.sin(0.2 * t)),
            "rssi": int(_clamp(82 - 6 * abs(math.sin(0.15 * t)), 0, 100)),
            "cog": round(cog, 1),
            "hdop": 0.7,
            "vdop": 1.1,
            "gps_vel": round(speed, 2),
            "ready": connected,
            "health_reason": "OK" if connected else "LINK",
            "health_message": "System ready" if connected else "Vehicle not connected",
            "extra": {},
        }


class BackendRuntimeSource:
    """Drains the backend's mirrored telemetry queue into HUD frames.

    Field mapping from backend/mavlink/telemetry_worker.py event payloads:
        attitude: roll/pitch/yaw (radians)  -> deg
        position: lat/lon/alt               -> lat/lon/altitude
        battery:  voltage/remaining         -> battery_v/battery_pct
        gps_raw:  fix_type/satellites/cog/vel/hdop/vdop -> ...
        signal:   percent                   -> rssi
        velocity: ground/speed (VFR_HUD m/s) -> speed
        heartbeat: armed/mode               -> armed/mode

    Health (ready/reason/last_message) flows as separate `health` events on
    the backend event bus — subscribed in application.py and stored here so
    the HUD can show the web's NOT READY / KILL SWITCH status pill states.
    """

    name = "gcs-backend"

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._telemetry_queue = runtime.telemetry_queue
        self._latest: dict = {}
        self._connected = False
        self._armed = False
        self._mode = "UNKNOWN"
        # Latest health snapshot (from health events, mirroring web useHealthStore)
        self._health: dict = {"ready": False, "reason": "INIT", "message": "Initializing..."}

    def on_backend_event(self, event: dict) -> None:
        """Called (main thread) for each backend event; health is tracked here."""
        if event.get("type") == "health":
            data = event.get("data") or {}
            if "ready" in data:
                self._health = {
                    "ready": bool(data.get("ready", False)),
                    "reason": str(data.get("reason", self._health.get("reason", "INIT"))),
                    "message": str(data.get("last_message", data.get("message", ""))),
                }

    def poll(self) -> dict | None:
        # Drain the queue; keep only the newest event (10 Hz publish rate,
        # 10 Hz UI timer — normally at most one pending).
        while True:
            try:
                event = self._telemetry_queue.get_nowait()
            except Empty:
                break
            if event.get("type") != "telemetry":
                continue
            self._latest = event
            self._connected = bool(event.get("connected", False))
            data = event.get("data") or {}
            hb = data.get("heartbeat") or {}
            self._armed = bool(hb.get("armed", False))
            self._mode = hb.get("mode", "UNKNOWN")

        if not self._latest:
            return None  # nothing yet — controller keeps last frame

        data = self._latest.get("data") or {}
        att = data.get("attitude") or {}
        pos = data.get("position") or {}
        bat = data.get("battery") or {}
        gps = data.get("gps_raw") or {}
        sig = data.get("signal") or {}
        vel = data.get("velocity") or {}

        yaw_deg = (math.degrees(att.get("yaw", 0.0)) % 360.0) if att else 0.0
        cog = gps.get("cog")
        speed = float(vel.get("speed", 0.0) or 0.0)
        # HEADING is where the NOSE points (yaw) — what the camera sees and what
        # the map marker/compass must show. The web policy of substituting GPS
        # course while moving made the HUD heading disagree with the video for
        # any multirotor that isn't flying nose-first. Course is exposed
        # separately for the GPS panel.
        heading = yaw_deg
        course = float(cog) % 360.0 if (cog is not None and speed >= COG_MIN_SPEED_MS) else None
        remaining = bat.get("remaining")
        battery_pct = float(remaining) if remaining is not None else -1.0

        return {
            "connected": self._connected,
            "armed": self._armed,
            "mode": self._mode,
            "state": self._runtime.state_worker.state if hasattr(self._runtime, "state_worker") else "UNKNOWN",
            "speed": speed,
            "altitude": float(pos.get("alt", 0.0) or 0.0),   # metres above HOME
            "climb": float(vel.get("vertical", 0.0) or 0.0),
            "heading": round(heading, 1),
            "course": None if course is None else round(course, 1),
            "alt_msl": pos.get("alt_msl"),
            "roll": math.degrees(att.get("roll", 0.0)) if att else 0.0,
            "pitch": math.degrees(att.get("pitch", 0.0)) if att else 0.0,
            "lat": pos.get("lat"),
            "lon": pos.get("lon"),
            "battery_pct": battery_pct,
            "battery_v": float(bat.get("voltage", 0.0) or 0.0),
            "gps_fix": int(gps.get("fix_type", 0) or 0),
            "sats": int(gps.get("satellites", 0) or 0),
            "rssi": int(sig.get("percent") or 0),
            "cog": cog,
            "hdop": gps.get("hdop"),
            "vdop": gps.get("vdop"),
            "gps_vel": gps.get("vel"),
            "ready": bool(self._health.get("ready", False)),
            "health_reason": self._health.get("reason", "INIT"),
            "health_message": self._health.get("message", ""),
            "extra": {"battery": bat, "gps_raw": gps, "signal": sig, "velocity": vel},
        }


class DisconnectedSource:
    """Honest no-vehicle source: always reports DISCONNECTED.

    Used when no backend is configured and simulation was not explicitly
    requested. The HUD shows NO LINK — it never invents a vehicle.
    """

    name = "disconnected"

    def poll(self) -> dict:
        return {
            "connected": False,
            "armed": False,
            "mode": "STANDBY",
            "state": "DISCONNECTED",
            "ready": False,
            "health_reason": "LINK",
            "health_message": "Vehicle not connected",
            "extra": {},
        }


def build_source(pre_start=None):
    """Telemetry source selection — NEVER silently fakes a vehicle:

    * GH_SIM=1 (or --sim)  → simulated flight, clearly labelled in the HUD.
    * GH_BACKEND_PATH set  → that backend ("none" explicitly disables).
    * GH_BACKEND_PATH unset→ attach the VENDORED backend shipped in this
      repository (backend/mavlink) — the desktop is self-contained. The HUD
      stays DISCONNECTED until a real vehicle heartbeat arrives either way.
    * backend failed       → DisconnectedSource: the app runs and the HUD is
      honest about having no vehicle link.
    """
    if os.environ.get("GH_SIM", "") not in ("", "0"):
        return SimulatedSource(), "simulation requested (GH_SIM=1)"

    path = os.environ.get("GH_BACKEND_PATH", "")
    reason = None
    if path.lower() == "none":
        return DisconnectedSource(), "backend disabled (GH_BACKEND_PATH=none)"
    if not path:
        from app.backend.runtime import VENDORED_BACKEND

        path = str(VENDORED_BACKEND)
        reason = f"vendored backend at {path}"

    try:
        from app.backend.runtime import BackendRuntime

        runtime = BackendRuntime(Path(path).expanduser().resolve())
        if pre_start is not None:
            # Apply the operator's saved CONNECTION settings before the first
            # connect attempt (otherwise gcs.env's target is tried first).
            pre_start(runtime)
        runtime.start()
        return BackendRuntimeSource(runtime), reason
    except Exception as exc:  # noqa: BLE001 — surface the failure honestly
        return (
            DisconnectedSource(),
            f"backend runtime unavailable ({exc}) — NO LINK",
        )
