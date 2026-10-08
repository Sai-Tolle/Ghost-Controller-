"""Telemetry bridge: the single seam between vehicle state and the QML HUD.

The controller owns a frame dict exposed to QML as a QVariantMap
(`Telemetry.telemetry`) plus a derived alert list (`Telemetry.alerts`).
Sources push frames via `ingest_frame()`; the controller normalizes and
notifies. `start()` activates the built-in simulated source; milestone 2
calls `attach_source(RealBackendSource(...))` instead — see backend.py.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

_FRAME_DEFAULTS: dict = {
    "connected": False,
    "armed": False,
    "mode": "STANDBY",
    "state": "DISCONNECTED",
    "speed": 0.0,
    "altitude": 0.0,
    "climb": 0.0,
    "heading": 0.0,
    "roll": 0.0,
    "pitch": 0.0,
    "lat": None,
    "lon": None,
    "battery_pct": -1.0,      # -1 = unknown (no reading yet); never show 0 %
    "battery_v": 0.0,
    "gps_fix": 0,
    "sats": 0,
    "rssi": 0,
    # web-gcs parity fields
    "cog": None,
    "hdop": None,
    "vdop": None,
    "gps_vel": None,
    "ready": False,
    "health_reason": "INIT",
    "health_message": "",
    # raw sub-dicts for panels (velocity.source drives the SPEED "EKF" note).
    # Missing from the defaults, _normalize() dropped it and the note never showed.
    "extra": {},
    "battery_pct_vehicle": -1.0,     # raw vehicle reading (kept when a voltage profile is active)
    "battery_cell_v": None,
    "battery_source": "vehicle",     # "vehicle" | "voltage"
    "battery_warn": 30.0,
    "battery_crit": 15.0,
    "course": None,          # GPS course over ground while moving (deg) or None
    "alt_msl": None,
}


def _normalize(frame: dict) -> dict:
    out = dict(_FRAME_DEFAULTS)
    for key in out:
        if key in frame:
            out[key] = frame[key]
    return out


def derive_alerts(frame: dict) -> list[dict]:
    """Safety-first derived alerts. NOTE: no alert for a missing link — the
    TopBar and the flight view both render a dedicated NO LINK state, and a
    duplicate red banner added nothing but noise.

    Each alert carries a stable `id` so the HUD banner can retire (mute) it
    on click; conditions re-arm after the mute TTL expires or the value
    returns to healthy and trips again."""
    alerts: list[dict] = []
    if not frame["connected"]:
        return alerts
    pct = frame["battery_pct"]
    # pct < 0 means "no battery reading yet" — it used to read as 0 % and raised
    # a false "Battery critical 0%" the moment a vehicle connected.
    crit, warn = frame.get("battery_crit", 15.0), frame.get("battery_warn", 30.0)
    if 0 <= pct < crit:
        alerts.append({"id": "batt-critical", "level": "danger",
                       "text": f"Battery critical {pct:.0f}%"})
    elif 0 <= pct < warn:
        alerts.append({"id": "batt-low", "level": "warn",
                       "text": f"Battery low {pct:.0f}%"})
    if frame["gps_fix"] <= 1:       # 0 = no GPS, 1 = no fix (was only 0)
        alerts.append({"id": "gps-nofix", "level": "warn", "text": "No GPS fix"})
    elif frame["gps_fix"] < 3:
        alerts.append({"id": "gps-2d", "level": "warn", "text": "GPS 2D fix only"})
    # rssi == 0 means the radio does not report a signal quality (e.g. USB
    # telemetry) — alerting "Weak signal 0%" on every such link was noise.
    if 0 < frame["rssi"] < 40:
        alerts.append({"id": "weak-signal", "level": "warn",
                       "text": f"Weak signal {frame['rssi']}%"})
    return alerts


class TelemetryController(QObject):
    telemetryChanged = Signal()
    sourceChanged = Signal()
    alertsChanged = Signal()
    positionTrackChanged = Signal()

    def __init__(self, parent=None, data_lake=None) -> None:
        super().__init__(parent)
        self._frame = dict(_FRAME_DEFAULTS)
        self._alerts: list[dict] = []
        self._track: list[list[float]] = []
        self._source_name = "disconnected"
        self._external = None  # M2: BackendRuntimeSource / SimulatedSource
        self._battery = None   # BatteryController (operator battery profile)
        self._lake = data_lake  # M3: DataLakeController (producer-side feed)
        self._backend_alerts: list[dict] = []  # {level, text, expires_at}
        # Click-dismissed derived alerts: id → muted-until (monotonic).
        # Backend one-shot alerts are removed outright instead.
        self._muted: dict[str, float] = {}
        self._MUTE_TTL = 60.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)  # 10 Hz — matches backend telemetry cadence
        self._timer.timeout.connect(self._tick)

    def set_battery(self, battery) -> None:
        """Attach the battery profile; re-derive the frame whenever it changes."""
        self._battery = battery
        battery.profileChanged.connect(self._reapply_battery)

    def _reapply_battery(self) -> None:
        if self._battery is not None:
            self._frame = self._battery.apply_to_frame(self._frame)
            self._sync_backend_alerts()
            self.telemetryChanged.emit()

    # ---- QML API ---------------------------------------------------------

    @Property("QVariantMap", notify=telemetryChanged)
    def telemetry(self) -> dict:  # noqa: N802
        return self._frame

    @Property(str, notify=sourceChanged)
    def source(self) -> str:  # noqa: N802
        return self._source_name

    @Property("QVariantList", notify=alertsChanged)
    def alerts(self) -> list:  # noqa: N802
        return self._alerts

    @Property("QVariantList", notify=positionTrackChanged)
    def positionTrack(self) -> list:  # noqa: N802
        """Flown track as [[lat, lon], ...], capped for the map canvas."""
        return self._track

    def _append_track(self, frame: dict) -> None:
        lat, lon = frame.get("lat"), frame.get("lon")
        if lat is None or lon is None or not frame.get("connected"):
            return
        if self._track and self._track[-1] == [lat, lon]:
            return
        self._track.append([float(lat), float(lon)])
        if len(self._track) > 600:
            self._track = self._track[-600:]
        self.positionTrackChanged.emit()

    # NOTE: no setMode slot on purpose — mode changes must go through
    # Vehicle.setMode so the backend command_guard/preflight stack applies.
    # (The old slot mutated the local frame only, faking a mode change that
    # was never sent to the vehicle.)

    @Slot(str, str, result=int)
    def pushBackendAlert(self, level: str, message: str) -> int:  # noqa: N802
        """Surface a proven-backend alert event (state/health worker) in the
        HUD alert stream. Returns the alert's id so callers can retire it
        early; otherwise it self-expires after `ttl_s`."""
        return self._push_backend_alert(level, message)

    def _push_backend_alert(self, level: str, message: str, ttl_s: float = 10.0) -> int:
        alert_id = int(time.monotonic() * 1000) & 0x7FFFFFFF
        self._backend_alerts.append({
            "id": alert_id,
            "level": "danger" if str(level).lower() in ("danger", "critical", "error") else "warn",
            "text": str(message),
            "expires_at": time.monotonic() + ttl_s,
        })
        self._sync_backend_alerts()
        return alert_id

    def retireBackendAlert(self, alert_id: int) -> None:  # noqa: N802
        self._backend_alerts = [a for a in self._backend_alerts if a["id"] != alert_id]
        self._sync_backend_alerts()

    @Slot("QVariant")
    def retireAlert(self, alert_id) -> None:  # noqa: N802
        """HUD banner click-to-dismiss. Numeric ids are one-shot backend
        alerts (removed); string ids are re-derived conditions (muted for a
        TTL so the 10 Hz re-derivation does not instantly re-show them)."""
        if isinstance(alert_id, bool):
            return
        if isinstance(alert_id, int):
            self.retireBackendAlert(alert_id)
            return
        if isinstance(alert_id, float) and alert_id.is_integer():
            self.retireBackendAlert(int(alert_id))
            return
        key = str(alert_id)
        if key and key not in ("None", "undefined"):
            self._muted[key] = time.monotonic() + self._MUTE_TTL
            self._sync_backend_alerts()

    def _sync_backend_alerts(self) -> None:
        now = time.monotonic()
        self._backend_alerts = [a for a in self._backend_alerts if a["expires_at"] > now]
        if self._muted:
            self._muted = {k: until for k, until in self._muted.items() if until > now}
        alerts = [a for a in derive_alerts(self._frame) if a["id"] not in self._muted] + [
            {"id": a["id"], "level": a["level"], "text": a["text"]} for a in self._backend_alerts
        ]
        alerts_changed = alerts != self._alerts
        self._alerts = alerts
        if alerts_changed:
            self.alertsChanged.emit()

    # ---- lifecycle -------------------------------------------------------

    @Slot()
    def start(self) -> None:
        # Source selection/attachment happens in application.py (build_source);
        # this only starts the 10 Hz UI timer.
        self._timer.start()

    def attach_source(self, source) -> None:
        """Milestone-2 seam: object exposing .name and .poll() -> dict|None."""
        self._external = source
        self._source_name = getattr(source, "name", "external")
        self.sourceChanged.emit()

    def ingest_frame(self, frame: dict) -> None:
        self._frame = _normalize(frame)
        self._append_track(self._frame)
        self.telemetryChanged.emit()

    # ---- internal --------------------------------------------------------

    def _tick(self) -> None:
        # One frame source only (attached in application.py). No implicit
        # fallback: with nothing attached the controller keeps the last
        # normalized frame — which is the DISCONNECTED defaults.
        if self._external is None:
            return
        frame = self._external.poll()
        if frame is None:
            return
        self._frame = _normalize(frame)
        if self._battery is not None:
            self._frame = self._battery.apply_to_frame(self._frame)
        self._sync_backend_alerts()
        self._append_track(self._frame)
        self._publish_lake()
        self.telemetryChanged.emit()

    _LAKE_MAP = {
        "vehicle/speed": "speed",
        "vehicle/altitude": "altitude",
        "vehicle/climb": "climb",
        "vehicle/heading": "heading",
        "vehicle/battery_pct": "battery_pct",
        "vehicle/battery_v": "battery_v",
        "vehicle/sats": "sats",
        "vehicle/rssi": "rssi",
        "vehicle/gps_fix": "gps_fix",
    }

    def _publish_lake(self) -> None:
        """Mirror the frame into the DataLake at the telemetry cadence.
        Dict writes are cheap; DataLake coalesces QML notification."""
        if self._lake is None:
            return
        for var_id, key in self._LAKE_MAP.items():
            self._lake.set(var_id, self._frame.get(key))
        self._lake.set("vehicle/connected", self._frame.get("connected", False))
        self._lake.set("vehicle/armed", self._frame.get("armed", False))
        self._lake.set("vehicle/mode", self._frame.get("mode", ""))
