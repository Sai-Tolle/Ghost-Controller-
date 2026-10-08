"""VehicleController: commands + preflight/health state for the QML HUD.

Commands are submitted to the backend's cmd_queue — the identical queue the
web GCS's REST API uses — so command_guard, preflight and mission-safety
validation in the proven backend apply unchanged. This controller NEVER talks
MAVLink directly.

Backend events consumed here (mirroring the web stores):
    preflight       -> preflight snapshot {can_arm, overall_status, checks}
    state           -> {state, armed, mode} debounced machine (useVehicleStore)
    health          -> {ready, reason, last_message} (useHealthStore)
    connection      -> autopilot/vehicle_type detection (web /vehicle/info)
    command_result  -> last action result for HUD feedback

The web's ModeSelector groups modes per firmware; `availableModes` mirrors
the backend mode_manager's mode table for the DETECTED autopilot.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

# Mode catalogue (web modeConfig.ts / backend mode_manager.py), grouped like
# the web dropdown: MANUAL / ASSISTED / AUTO / ADVANCED.
_MODE_TABLE: dict[str, dict] = {
    # PX4
    "MANUAL":     {"label": "Manual",        "group": "MANUAL",   "autopilot": "PX4",       "color": "danger"},
    "STABILIZED": {"label": "Stabilized",    "group": "MANUAL",   "autopilot": "PX4",       "color": "lime"},
    "ACRO":       {"label": "Acro",          "group": "MANUAL",   "autopilot": "both",      "color": "danger"},
    "RATTITUDE":  {"label": "Rattitude",     "group": "MANUAL",   "autopilot": "PX4",       "color": "danger"},
    "ALTCTL":     {"label": "Altitude",      "group": "ASSISTED", "autopilot": "PX4",       "color": "lime"},
    "POSCTL":     {"label": "Position",      "group": "ASSISTED", "autopilot": "PX4",       "color": "lime"},
    "LOITER":     {"label": "Loiter",        "group": "AUTO",     "autopilot": "both",      "color": "lime"},
    "MISSION":    {"label": "Mission",       "group": "AUTO",     "autopilot": "PX4",       "color": "warn"},
    "RTL":        {"label": "RTL",           "group": "AUTO",     "autopilot": "both",      "color": "warn"},
    "LAND":       {"label": "Land",          "group": "AUTO",     "autopilot": "both",      "color": "warn"},
    "TAKEOFF":    {"label": "Takeoff",       "group": "AUTO",     "autopilot": "PX4",       "color": "warn"},
    "FOLLOW_ME":  {"label": "Follow Me",     "group": "AUTO",     "autopilot": "PX4",       "color": "info"},
    "PRECLAND":   {"label": "Precision Land", "group": "AUTO",    "autopilot": "PX4",       "color": "warn"},
    "AUTO_READY": {"label": "Auto Ready",    "group": "AUTO",     "autopilot": "PX4",       "color": "warn"},
    "OFFBOARD":   {"label": "Offboard",      "group": "ADVANCED", "autopilot": "PX4",       "color": "info"},
    # ArduPilot
    "STABILIZE":  {"label": "Stabilize",     "group": "MANUAL",   "autopilot": "ArduPilot", "color": "lime"},
    "ALT_HOLD":   {"label": "Alt Hold",      "group": "MANUAL",   "autopilot": "ArduPilot", "color": "lime"},
    "DRIFT":      {"label": "Drift",         "group": "MANUAL",   "autopilot": "ArduPilot", "color": "danger"},
    "SPORT":      {"label": "Sport",         "group": "MANUAL",   "autopilot": "ArduPilot", "color": "danger"},
    "AUTO":       {"label": "Auto",          "group": "AUTO",     "autopilot": "ArduPilot", "color": "warn"},
    "GUIDED":     {"label": "Guided",        "group": "AUTO",     "autopilot": "ArduPilot", "color": "info"},
    "CIRCLE":     {"label": "Circle",        "group": "AUTO",     "autopilot": "ArduPilot", "color": "lime"},
    "POSHOLD":    {"label": "Position Hold", "group": "AUTO",     "autopilot": "ArduPilot", "color": "lime"},
}

_GROUP_ORDER = ("MANUAL", "ASSISTED", "AUTO", "ADVANCED")


def modes_for(autopilot: str) -> list[dict]:
    """Modes available for `autopilot`, in web dropdown order (grouped)."""
    out: list[dict] = []
    for group in _GROUP_ORDER:
        for mode_id, cfg in _MODE_TABLE.items():
            if cfg["group"] != group:
                continue
            if cfg["autopilot"] in (autopilot, "both"):
                out.append({
                    "id": mode_id,
                    "label": cfg["label"],
                    "group": group,
                    "color": cfg["color"],
                })
    return out


class VehicleController(QObject):
    preflightChanged = Signal()
    lastActionResultChanged = Signal()
    connectionChanged = Signal()
    vehicleStateChanged = Signal()
    healthChanged = Signal()
    takeoffAltitudeChanged = Signal()

    def __init__(self, runtime) -> None:
        super().__init__()
        self._runtime = runtime
        self._preflight: dict = {}
        self._last_action: dict = {"command": "", "result": None}
        self._firmware = ""
        self._vehicle_type = ""
        self._vehicle_state = "DISCONNECTED"
        self._health: dict = {"ready": False, "reason": "INIT", "message": "Initializing..."}
        self._modes: list[dict] = modes_for("UNKNOWN")
        from app.bridge.settings import app_settings
        try:
            self._takeoff_alt = float(app_settings().value("vehicle/takeoffAlt", 10.0))
        except (TypeError, ValueError):
            self._takeoff_alt = 10.0
        self._takeoff_alt = max(1.0, min(120.0, self._takeoff_alt))
        # Backend events arrive on the runtime's worker threads; buffer them
        # and apply on the main thread so QML-visible state is only ever
        # mutated where QML reads it.
        self._pending_events: list[dict] = []
        self._events_lock = threading.Lock()
        self._flush = QTimer(self)
        self._flush.setInterval(50)
        self._flush.timeout.connect(self._drain_events)
        self._flush.start()
        if runtime is not None:
            runtime.subscribe(self._on_event)

    # ---- events ----------------------------------------------------------

    def _on_event(self, event: dict) -> None:
        with self._events_lock:
            self._pending_events.append(dict(event))

    def _drain_events(self) -> None:
        with self._events_lock:
            events, self._pending_events = self._pending_events, []
        for event in events:
            etype = event.get("type")
            if etype == "preflight":
                self._preflight = event.get("data") or {}
                self.preflightChanged.emit()
            elif etype == "command_result":
                self._last_action = {
                    "command": event.get("command", ""),
                    "result": event.get("result"),
                }
                self.lastActionResultChanged.emit()
            elif etype == "connection":
                # MAVLinkConnection._publish_connection wraps details in
                # `payload`: {status, autopilot, vehicle_type, system, ...}.
                # Reading top-level keys (pre-fix) silently lost the autopilot
                # detection → FIRMWARE stuck on UNKNOWN and the mode dropdown
                # fell back to the 4 shared "both" modes only.
                payload = event.get("payload") or {}
                if str(payload.get("status", "")) == "connected":
                    self._firmware = str(payload.get("autopilot") or "")
                    self._vehicle_type = str(payload.get("vehicle_type") or "")
                    self._modes = modes_for(self._firmware)
                    self.connectionChanged.emit()
            elif etype == "state":
                data = event.get("data") or {}
                self._vehicle_state = str(data.get("state", self._vehicle_state))
                self.vehicleStateChanged.emit()
            elif etype == "health":
                data = event.get("data") or {}
                if "ready" in data:
                    self._health = {
                        "ready": bool(data.get("ready", False)),
                        "reason": str(data.get("reason", self._health.get("reason", "INIT"))),
                        "message": str(data.get("last_message", data.get("message", ""))),
                    }
                    self.healthChanged.emit()

    # ---- QML API ---------------------------------------------------------

    @Property("QVariantMap", notify=preflightChanged)
    def preflight(self) -> dict:  # noqa: N802
        return self._preflight

    @Property("QVariantList", notify=preflightChanged)
    def preflightChecks(self) -> list:  # noqa: N802
        return self._preflight.get("checks", [])

    @Property(bool, notify=preflightChanged)
    def canArm(self) -> bool:  # noqa: N802
        return bool(self._preflight.get("can_arm", False))

    @Property(str, notify=preflightChanged)
    def preflightStatus(self) -> str:  # noqa: N802
        return str(self._preflight.get("overall_status", "WAITING"))

    @Property("QVariantMap", notify=lastActionResultChanged)
    def lastActionResult(self) -> dict:  # noqa: N802
        return self._last_action

    @Property(str, notify=connectionChanged)
    def firmware(self) -> str:  # noqa: N802
        """Autopilot firmware reported by the backend's connection event."""
        return self._firmware

    @Property("QVariantList", notify=connectionChanged)
    def availableModes(self) -> list:  # noqa: N802
        """Mode catalogue for the detected firmware (web ModeSelector parity)."""
        return self._modes

    @Property(str, notify=vehicleStateChanged)
    def vehicleState(self) -> str:  # noqa: N802
        return self._vehicle_state

    @Property("QVariantMap", notify=healthChanged)
    def health(self) -> dict:  # noqa: N802
        return self._health

    @Property(bool, notify=healthChanged)
    def healthReady(self) -> bool:  # noqa: N802
        return bool(self._health.get("ready", False))

    @Property(str, notify=healthChanged)
    def healthReason(self) -> str:  # noqa: N802
        return str(self._health.get("reason", "INIT"))

    @Property(str, notify=healthChanged)
    def healthMessage(self) -> str:  # noqa: N802
        return str(self._health.get("message", ""))

    @Property(float, notify=takeoffAltitudeChanged)
    def takeoffAltitude(self) -> float:  # noqa: N802
        """One takeoff height for the TAKEOFF button AND the mode-menu sequence
        (they used 25 m vs 10 m)."""
        return self._takeoff_alt

    @Slot(float)
    def setTakeoffAltitude(self, metres: float) -> None:  # noqa: N802
        from app.bridge.settings import app_settings
        self._takeoff_alt = max(1.0, min(120.0, float(metres)))
        s = app_settings()
        s.setValue("vehicle/takeoffAlt", self._takeoff_alt)
        s.sync()
        self.takeoffAltitudeChanged.emit()

    @Property(bool, constant=True)
    def commandable(self) -> bool:  # noqa: N802
        """True when a backend runtime is wired so commands actually go
        somewhere. QML uses this to disable (not just hide) flight actions."""
        return self._runtime is not None

    @Property(str, constant=True)
    def linkTarget(self) -> str:  # noqa: N802
        """Where the backend is (or would be) listening for a vehicle —
        MAVLINK_CONNECTION if set, else the serial-autodetect→UDP-fallback
        chain. Shown in the NO LINK overlay so 'why not connected' is
        answerable at a glance."""
        if self._runtime is None:
            return ""
        conn = getattr(self._runtime, "mav_conn", None)
        conn_string = getattr(conn, "connection_string", None) if conn else None
        if conn_string:
            return str(conn_string)
        return os.environ.get("MAVLINK_FALLBACK", "udpin:127.0.0.1:14550")

    # ---- commands (same queue as the web REST API) -----------------------

    @Slot(str)
    def setMode(self, mode: str) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.set_mode(mode)

    @Slot()
    def arm(self) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.arm()

    @Slot()
    def disarm(self) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.disarm()

    @Slot()
    def kill(self) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.kill()

    @Slot(float)
    def takeoff(self, altitude: float) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.takeoff(altitude)

    @Slot()
    def land(self) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.land()

    @Slot()
    def rtl(self) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.rtl()

    @Slot(float, float, float, float, float)
    def orbit(self, lat: float, lon: float, alt: float, radius: float, velocity: float) -> None:  # noqa: N802
        """LIVE ORBIT command (web /command/orbit parity) — goes through the
        same proven command_worker ORBIT path."""
        if self._runtime is not None:
            self._runtime.submit("ORBIT", {
                "lat": float(lat), "lon": float(lon), "alt": float(alt),
                "radius": float(radius), "velocity": float(velocity),
            })
