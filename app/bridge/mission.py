"""MissionController — waypoint & geofence planning for the QML mission view.

Owns the PLANNED mission (operator's intent, edited on the map) and pushes it
to the vehicle through the proven backend command stack:

    runtime.submit("MISSION_UPLOAD", {"mission": [...]})   — validated by
    mission_safety (preflight must pass, alts ≥ 1 m, LAND may be 0)
    runtime.submit("MISSION_DOWNLOAD") / ("MISSION_CLEAR")
    runtime.submit("FENCE_UPLOAD", {"fence": [...]}) / DOWNLOAD / CLEAR
    runtime.submit("MISSION_START")

Upload/download results arrive as `command_result` events, filtered here into
`lastResult` for the QML panels. The plan itself persists via QSettings so a
crash never loses a surveyed mission.

Payload shape (mirrors GCS/mavlink/mission_upload.py command_map):
    {"command": "TAKEOFF"|"WAYPOINT"|"LAND"|"RTL"|"ORBIT", "lat", "lon", "alt"}
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from app.bridge.settings import app_settings

DEFAULT_HOME = (47.397742, 8.545594)  # PX4 SITL Zurich home
DEFAULT_WP_ALT = 30.0

COMMANDS = ("WAYPOINT", "TAKEOFF", "LAND", "RTL", "ORBIT", "SURVEY", "LOITER_TO_ALT")

_EARTH_RADIUS_M = 6378137.0  # web MissionPlanner.tsx offsetToLatLon


def _offset_to_latlon(clat: float, clon: float, dx: float, dy: float) -> tuple[float, float]:
    """Meters offset (x=east, y=north) from a center → (lat, lon).
    Identical math to the web MissionPlanner's offsetToLatLon."""
    dlat = (dy / _EARTH_RADIUS_M) * (180.0 / 3.141592653589793)
    dlon = (dx / (_EARTH_RADIUS_M * __import__('math').cos((clat * 3.141592653589793) / 180.0))) * (180.0 / 3.141592653589793)
    return clat + dlat, clon + dlon


def generate_survey_grid(center_lat: float, center_lon: float, width: float,
                         height: float, spacing: float, angle_deg: float,
                         alt: float) -> list[dict]:
    """Boustrophedon (lawn-mower) survey grid — identical algorithm to the
    web MissionPlanner's generateSurveyGrid: rotated rectangle footprint,
    vertical lines spaced `spacing` m apart, serpentine direction, two
    waypoints (bottom, top) per line, all at `alt` meters.

    Returns [{lat, lon, alt, command: WAYPOINT}, ...].
    """
    import math

    # Guard the loop below: spacing <= 0 (or NaN) never advances `x`, so the old
    # code spun forever on the GUI thread when the operator typed 0 spacing.
    if not (spacing > 0 and width > 0 and height > 0):
        return []
    if width / spacing > 500:           # absurd grids would freeze the planner
        return []
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    wps: list[dict] = []
    go_up = True
    x = -width / 2.0
    while x <= width / 2.0 + 1e-9:
        y_start = -height / 2.0 if go_up else height / 2.0
        y_end = height / 2.0 if go_up else -height / 2.0
        for y in (y_start, y_end):
            rx = x * cos_a - y * sin_a
            ry = x * sin_a + y * cos_a
            lat, lon = _offset_to_latlon(center_lat, center_lon, rx, ry)
            wps.append({
                "lat": round(lat, 7), "lon": round(lon, 7),
                "alt": float(alt), "command": "WAYPOINT",
            })
        go_up = not go_up
        x += spacing
    return wps


def _fence_latlon(p) -> list[float]:
    """Fence point as [lat, lon]; accepts both the backend download shape
    ({lat, lon}) and the desktop plan shape ([lat, lon])."""
    if isinstance(p, dict):
        return [float(p.get("lat", 0.0)), float(p.get("lon", p.get("lng", 0.0)))]
    return [float(p[0]), float(p[1])]


def point_inside_fence(lat: float, lon: float, fence: list) -> bool:
    """Ray-casting point-in-polygon (web parity: isPointInsideFence)."""
    if len(fence) < 3:
        return True
    inside = False
    pts = [_fence_latlon(p) for p in fence]
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        intersect = ((yi > lon) != (yj > lon)) and (
            lat < ((xj - xi) * (lon - yi)) / (yj - yi) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside

_PLANNER_COMMANDS = (
    "MISSION_UPLOAD", "MISSION_DOWNLOAD", "MISSION_CLEAR", "MISSION_START",
    "FENCE_UPLOAD", "FENCE_DOWNLOAD", "FENCE_CLEAR",
)


class MissionController(QObject):
    waypointsChanged = Signal()
    fenceChanged = Signal()
    selectionChanged = Signal()
    lastResultChanged = Signal()
    homeChanged = Signal()
    orbitTargetChanged = Signal()

    def __init__(self, runtime=None, parent=None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._settings = app_settings()
        self._waypoints: list[dict] = []
        self._fence: list[list[float]] = []
        self._selected = -1
        self._orbit_radius = 15.0      # web defaults
        self._orbit_velocity = 2.0
        self._last_result: dict = {"command": "", "result": None}
        self._orbit_target: list[float] | None = None   # [lat, lon, radius]
        self._home = list(DEFAULT_HOME)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_now)
        self._load()
        # Command results arrive on backend worker threads; apply on the main
        # thread (same pattern as VehicleController).
        self._pending_events: list[dict] = []
        self._events_lock = threading.Lock()
        self._flush = QTimer(self)
        self._flush.setInterval(50)
        self._flush.timeout.connect(self._drain_events)
        self._flush.start()
        if runtime is not None:
            runtime.subscribe(self._on_event)

    # ---- persistence -------------------------------------------------------

    def _load(self) -> None:
        for key, attr in (("mission/waypoints", "_waypoints"), ("mission/fence", "_fence")):
            raw = self._settings.value(key, "")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, list):
                setattr(self, attr, data)

    def _save(self) -> None:
        """Coalesce writes: dragging a marker fired a disk sync per mouse move."""
        self._save_timer.start()

    def _save_now(self) -> None:
        self._settings.setValue("mission/waypoints", json.dumps(self._waypoints))
        self._settings.setValue("mission/fence", json.dumps(self._fence))
        self._settings.sync()

    def flush(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    # ---- events -------------------------------------------------------------

    def _on_event(self, event: dict) -> None:
        with self._events_lock:
            self._pending_events.append(dict(event))

    def _drain_events(self) -> None:
        with self._events_lock:
            events, self._pending_events = self._pending_events, []
        for event in events:
            self._apply_command_result(event)

    def _apply_command_result(self, event: dict) -> None:
        if event.get("type") != "command_result":
            return
        command = event.get("command", "")
        if command in _PLANNER_COMMANDS:
            self._last_result = {"command": command, "result": event.get("result")}
            self.lastResultChanged.emit()
            result = event.get("result") or {}
            # Adopt the vehicle's mission after a successful round-trip. The
            # backend returns {"mission": [...]} / {"fence": [...]} without a
            # "success" key, so keying on it meant downloads were never adopted.
            ok = "error" not in result
            if command == "MISSION_DOWNLOAD" and ok:
                items = result.get("mission")
                if isinstance(items, list):
                    # keep navigation items only; DO_*/UNKNOWN_* items carry
                    # lat/lon 0 and would land at (0, 0) on the map.
                    nav = [w for w in items
                           if not str(w.get("command", "")).startswith("UNKNOWN_")]
                    self._waypoints = [self._sanitize_wp(w, i) for i, w in enumerate(nav)]
                    self._selected = -1
                    self._save()
                    self.waypointsChanged.emit()
                    self.selectionChanged.emit()
            elif command == "FENCE_DOWNLOAD" and ok:
                pts = result.get("fence")
                if isinstance(pts, list):
                    self._fence = [_fence_latlon(p) for p in pts]
                    self._save()
                    self.fenceChanged.emit()
            elif command == "ORBIT":
                result = event.get("result") or {}
                if not result.get("error"):
                    # web parity: visualize the active orbit on both maps
                    data = event.get("data") or {}
                    # (target stored by orbitAt() at send time; radius may be updated)
                    self.orbitTargetChanged.emit()

    @staticmethod
    def _sanitize_wp(wp: dict, index: int) -> dict:
        command = str(wp.get("command", "WAYPOINT")).upper()
        if command not in COMMANDS:
            command = "WAYPOINT"
        try:
            lat = float(wp.get("lat"))
        except (TypeError, ValueError):
            lat = 0.0
        try:
            lon = float(wp.get("lon"))
        except (TypeError, ValueError):
            lon = 0.0
        try:
            alt = float(wp.get("alt", wp.get("altitude", DEFAULT_WP_ALT)))
        except (TypeError, ValueError):
            alt = DEFAULT_WP_ALT
        return {"seq": index, "command": command, "lat": lat, "lon": lon, "alt": alt}

    # ---- QML properties ------------------------------------------------------

    @Property("QVariantList", notify=waypointsChanged)
    def waypoints(self) -> list:  # noqa: N802
        return list(self._waypoints)

    @Property("QVariantList", notify=fenceChanged)
    def fencePoints(self) -> list:  # noqa: N802
        return list(self._fence)

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:  # noqa: N802
        return self._selected

    @Property("QVariantMap", notify=lastResultChanged)
    def lastResult(self) -> dict:  # noqa: N802
        return self._last_result

    @Property("QVariantList", notify=orbitTargetChanged)
    def orbitTarget(self) -> list:  # noqa: N802
        """Active orbit visualization: [lat, lon, radius] or []."""
        return list(self._orbit_target) if self._orbit_target else []

    @Slot()
    def clearResult(self) -> None:  # noqa: N802
        """Dismiss the planner's result toast."""
        self._last_result = {"command": "", "result": None}
        self.lastResultChanged.emit()

    @Property("QVariantList", notify=homeChanged)
    def home(self) -> list:  # noqa: N802
        return list(self._home)

    @Property(bool, constant=True)
    def commandable(self) -> bool:  # noqa: N802
        return self._runtime is not None

    def set_home(self, lat: float, lon: float) -> None:
        if (lat, lon) != tuple(self._home):
            self._home = [float(lat), float(lon)]
            self.homeChanged.emit()

    # ---- plan editing (QML slots) ---------------------------------------------

    @Slot()
    def beginPlan(self) -> None:  # noqa: N802
        """Planner entry point: seed the first waypoint at home if empty so
        'click map to add waypoints' always extends a visible plan."""
        if not self._waypoints:
            self.addWaypointAt(self._home[0] + 0.0008, self._home[1] + 0.0008)

    @Slot(float, float)
    def addWaypointAt(self, lat: float, lon: float) -> int:  # noqa: N802
        wp = {
            "seq": len(self._waypoints),
            "command": "TAKEOFF" if not self._waypoints else "WAYPOINT",
            "lat": round(float(lat), 7),
            "lon": round(float(lon), 7),
            "alt": DEFAULT_WP_ALT,
        }
        self._waypoints.append(wp)
        self._selected = len(self._waypoints) - 1
        self._save()
        self.waypointsChanged.emit()
        self.selectionChanged.emit()
        return self._selected

    @Slot(int, float, float)
    def moveWaypoint(self, seq: int, lat: float, lon: float) -> None:  # noqa: N802
        if 0 <= seq < len(self._waypoints):
            self._waypoints[seq]["lat"] = round(float(lat), 7)
            self._waypoints[seq]["lon"] = round(float(lon), 7)
            self._save()
            self.waypointsChanged.emit()

    @Slot(int, str)
    def setWaypointCommand(self, seq: int, command: str) -> None:  # noqa: N802
        command = str(command).upper()
        if 0 <= seq < len(self._waypoints) and command in COMMANDS:
            self._waypoints[seq]["command"] = command
            self._save()
            self.waypointsChanged.emit()

    @Slot(int, float)
    def setWaypointAlt(self, seq: int, alt: float) -> None:  # noqa: N802
        if 0 <= seq < len(self._waypoints):
            try:
                alt = float(alt)
            except (TypeError, ValueError):
                return
            self._waypoints[seq]["alt"] = max(0.0, alt)
            self._save()
            self.waypointsChanged.emit()

    @Slot(int)
    def selectWaypoint(self, seq: int) -> None:  # noqa: N802
        self._selected = int(seq)
        self.selectionChanged.emit()

    @Slot(int)
    def deleteWaypoint(self, seq: int) -> None:  # noqa: N802
        if 0 <= seq < len(self._waypoints):
            del self._waypoints[seq]
            for i, wp in enumerate(self._waypoints):
                wp["seq"] = i
            self._selected = min(self._selected, len(self._waypoints) - 1)
            self._save()
            self.waypointsChanged.emit()
            self.selectionChanged.emit()

    @Slot()
    def clearMission(self) -> None:  # noqa: N802
        self._waypoints = []
        self._selected = -1
        self._save()
        self.waypointsChanged.emit()
        self.selectionChanged.emit()

    # ---- fence editing -----------------------------------------------------------

    @Slot(float, float)
    def addFencePointAt(self, lat: float, lon: float) -> None:  # noqa: N802
        self._fence.append([round(float(lat), 7), round(float(lon), 7)])
        self._save()
        self.fenceChanged.emit()

    @Slot(int, float, float)
    def moveFencePoint(self, index: int, lat: float, lon: float) -> None:  # noqa: N802
        if 0 <= index < len(self._fence):
            self._fence[index] = [round(float(lat), 7), round(float(lon), 7)]
            self._save()
            self.fenceChanged.emit()

    @Slot(int)
    def deleteFencePoint(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._fence):
            del self._fence[index]
            self._save()
            self.fenceChanged.emit()

    @Slot()
    def clearFence(self) -> None:  # noqa: N802
        self._fence = []
        self._save()
        self.fenceChanged.emit()

    # ---- import / export (paths come from QML FileDialog `fileUrl`) -----------

    @Slot(str, result=bool)
    def importFromFile(self, path: str) -> bool:  # noqa: N802
        p = str(path)
        if p.startswith("file://"):
            from urllib.parse import unquote, urlsplit

            p = unquote(urlsplit(p).path)
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        except (OSError, ValueError):
            self._last_result = {"command": "IMPORT", "result": {"success": False,
                                                                 "error": f"cannot read {p}"}}
            self.lastResultChanged.emit()
            return False
        if isinstance(data, dict):
            items = data.get("mission")
            fence = data.get("fence")
        else:
            items, fence = data, None
        # Only replace what the file actually contains. Importing a fence-only
        # file used to wipe the whole mission.
        if isinstance(items, list):
            self._waypoints = [self._sanitize_wp(w, i) for i, w in enumerate(items)]
        if isinstance(fence, list):
            try:
                self._fence = [_fence_latlon(p_) for p_ in fence]
            except (TypeError, ValueError, IndexError, KeyError):
                self._fence = []
        self._selected = -1
        self._save()
        self.waypointsChanged.emit()
        self.fenceChanged.emit()
        self.selectionChanged.emit()
        self._last_result = {"command": "IMPORT", "result": {"success": True,
                                                             "count": len(self._waypoints)}}
        self.lastResultChanged.emit()
        return True

    @Slot(str, result=bool)
    def exportMissionTo(self, path: str) -> bool:  # noqa: N802
        return self._export(path, {"mission": self._waypoints})

    @Slot(str, result=bool)
    def exportFenceTo(self, path: str) -> bool:  # noqa: N802
        return self._export(path, {"fence": self._fence})

    def _export(self, path: str, payload: dict) -> bool:
        p = self._url_to_path(path)
        if not p.lower().endswith(".json"):
            p += ".json"
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            self._last_result = {"command": "EXPORT", "result": {
                "success": False, "error": f"cannot write {p}"}}
            self.lastResultChanged.emit()
            return False
        self._last_result = {"command": "EXPORT", "result": {
            "success": True, "count": len(payload.get("mission", payload.get("fence", [])))}}
        self.lastResultChanged.emit()
        return True

    @staticmethod
    def _url_to_path(path: str) -> str:
        p = str(path)
        if p.startswith("file:"):
            from urllib.parse import unquote, urlsplit
            from urllib.request import url2pathname
            p = url2pathname(unquote(urlsplit(p).path))   # handles file:///C:/... on Windows
        return p

    @Slot(str, result=bool)
    def exportToFile(self, path: str) -> bool:  # noqa: N802
        p = str(path)
        if p.startswith("file://"):
            from urllib.parse import unquote, urlsplit

            p = unquote(urlsplit(p).path)
        if not p.lower().endswith(".json"):
            p += ".json"
        payload = {"mission": self._waypoints, "fence": self._fence}
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            self._last_result = {"command": "EXPORT", "result": {"success": False,
                                                                 "error": f"cannot write {p}"}}
            self.lastResultChanged.emit()
            return False
        self._last_result = {"command": "EXPORT", "result": {"success": True,
                                                             "count": len(self._waypoints)}}
        self.lastResultChanged.emit()
        return True

    # ---- vehicle round-trips (proven command stack) ------------------------------

    def _submit(self, cmd_type: str, data: dict | None = None) -> bool:
        if self._runtime is None:
            self._last_result = {"command": cmd_type,
                                 "result": {"success": False,
                                            "error": "no backend runtime (GH_BACKEND_PATH unset)"}}
            self.lastResultChanged.emit()
            return False
        self._runtime.submit(cmd_type, data)
        return True

    @Slot()
    def upload(self) -> None:  # noqa: N802
        self._submit("MISSION_UPLOAD", {"mission": self._waypoints})

    @Slot()
    def download(self) -> None:  # noqa: N802
        self._submit("MISSION_DOWNLOAD")

    @Slot()
    def clearOnVehicle(self) -> None:  # noqa: N802
        self._submit("MISSION_CLEAR")

    @Slot()
    def uploadFence(self) -> None:  # noqa: N802
        # backend/mavlink/fence_upload.py expects [{lat, lon}, ...]; the plan
        # stores [[lat, lon], ...] — convert at the submit boundary.
        payload = [{"lat": p[0], "lon": p[1]} for p in self._fence]
        self._submit("FENCE_UPLOAD", {"fence": payload})

    @Slot()
    def downloadFence(self) -> None:  # noqa: N802
        self._submit("FENCE_DOWNLOAD")

    @Slot()
    def clearFenceOnVehicle(self) -> None:  # noqa: N802
        self._submit("FENCE_CLEAR")

    @Slot()
    def startMission(self) -> None:  # noqa: N802
        self._submit("MISSION_START")

    # ---- web-parity planning helpers ---------------------------------------

    @Slot(float, float, result=bool)
    def orbitAt(self, lat: float, lon: float) -> bool:  # noqa: N802
        """Send a LIVE ORBIT to (lat, lon) with the current radius/velocity
        from QML (web /command/orbit). Returns False (with a status result)
        when no backend is attached. The orbit ring is visualized on success.
        """
        if self._runtime is None:
            self._last_result = {"command": "ORBIT",
                                 "result": {"success": False,
                                            "error": "no backend runtime (GH_BACKEND_PATH unset)"}}
            self.lastResultChanged.emit()
            return False
        self._orbit_target = [float(lat), float(lon), self._orbit_radius]
        self.orbitTargetChanged.emit()
        self._runtime.submit("ORBIT", {
            "lat": float(lat), "lon": float(lon),
            "alt": 10.0, "radius": self._orbit_radius,
            "velocity": self._orbit_velocity,
        })
        return True

    @Slot(float)
    def setOrbitRadius(self, radius: float) -> None:  # noqa: N802
        self._orbit_radius = max(1.0, float(radius))

    @Slot(float)
    def setOrbitVelocity(self, velocity: float) -> None:  # noqa: N802
        self._orbit_velocity = float(velocity)

    @Slot(float, float, float, float, float, float, result="QVariantList")
    def previewSurvey(self, center_lat: float, center_lon: float, width: float,
                      height: float, spacing: float, angle: float, alt: float) -> list:  # noqa: N802
        """Survey footprint corners (web getSurveyPolygon) — 4 [lat, lon]
        pairs for the dashed preview polygon."""
        import math

        rad = math.radians(angle)
        corners = [(-width / 2, -height / 2), (width / 2, -height / 2),
                   (width / 2, height / 2), (-width / 2, height / 2)]
        out: list[list[float]] = []
        for x, y in corners:
            rx = x * math.cos(rad) - y * math.sin(rad)
            ry = x * math.sin(rad) + y * math.cos(rad)
            lat, lon = _offset_to_latlon(center_lat, center_lon, rx, ry)
            out.append([round(lat, 7), round(lon, 7)])
        return out

    @Slot(float, float, float, float, float, float, float, result=int)
    def generateSurvey(self, center_lat: float, center_lon: float, width: float,
                       height: float, spacing: float, angle: float, alt: float) -> int:  # noqa: N802
        """Append a boustrophedon survey grid at the clicked center (web
        generateSurveyGrid). Returns the number of waypoints generated."""
        wps = generate_survey_grid(center_lat, center_lon, width, height,
                                   spacing, angle, alt)
        self._waypoints.extend(wps)
        self._save()
        self.waypointsChanged.emit()
        self._last_result = {"command": "SURVEY",
                             "result": {"success": True, "count": len(wps)}}
        self.lastResultChanged.emit()
        return len(wps)

    @Slot(float, float, result=bool)
    def isInsideFence(self, lat: float, lon: float) -> bool:  # noqa: N802
        return point_inside_fence(lat, lon, self._fence)

    @Slot(result=bool)
    def isHomeInsideFence(self) -> bool:  # noqa: N802
        """Web parity: fence upload requires the CURRENT VEHICLE position
        (not the planned home) to be inside the polygon."""
        frame_ok = self._home and len(self._fence) >= 3
        if not frame_ok:
            return False
        return point_inside_fence(self._home[0], self._home[1], self._fence)

    @Slot(result=bool)
    def validateMission(self) -> bool:  # noqa: N802
        """Web parity pre-upload check: ≥1 waypoint, all inside the fence.
        Failures are surfaced via lastResult for the status bar."""
        if len(self._waypoints) < 1:
            self._last_result = {"command": "VALIDATE",
                                 "result": {"success": False, "error": "Need at least 1 waypoint"}}
            self.lastResultChanged.emit()
            return False
        for wp in self._waypoints:
            if not point_inside_fence(wp["lat"], wp["lon"], self._fence):
                self._last_result = {"command": "VALIDATE",
                                     "result": {"success": False,
                                                "error": "Waypoint outside geofence"}}
                self.lastResultChanged.emit()
                return False
        return True

    @Slot(str, result=bool)
    def importQgcWaypoints(self, path: str) -> bool:  # noqa: N802
        """Import a QGC WPL file (.waypoints/.txt) — web parity parse.
        MAV_CMD 22 → TAKEOFF, 21 → LAND, everything else WAYPOINT."""
        p = str(path)
        if p.startswith("file://"):
            from urllib.parse import unquote, urlsplit

            p = unquote(urlsplit(p).path)
        try:
            lines = Path(p).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            self._last_result = {"command": "IMPORT",
                                 "result": {"success": False, "error": f"cannot read {p}"}}
            self.lastResultChanged.emit()
            return False
        parsed: list[dict] = []
        for line in lines:
            if line.startswith("QGC") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 12:
                continue
            try:
                mav_cmd = int(float(parts[3]))
                lat = float(parts[8])
                lon = float(parts[9])
                alt = float(parts[10])
            except ValueError:
                continue
            command = "WAYPOINT"
            if mav_cmd == 22:
                command = "TAKEOFF"
            elif mav_cmd == 21:
                command = "LAND"
            parsed.append({"lat": lat, "lon": lon, "alt": alt, "command": command})
        self._waypoints = [self._sanitize_wp(w, i) for i, w in enumerate(parsed)]
        self._selected = -1
        self._save()
        self.waypointsChanged.emit()
        self.selectionChanged.emit()
        self._last_result = {"command": "IMPORT",
                             "result": {"success": True, "count": len(self._waypoints)}}
        self.lastResultChanged.emit()
        return True
