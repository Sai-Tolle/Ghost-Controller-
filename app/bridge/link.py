"""LinkController: CONNECTION settings for the MAVLink link.

What the operator can set (persisted in QSettings under link/*):
    mode          auto | udp | tcp | serial
    udp_role      udpin (listen — SITL, most radios/companions) | udpout (send to a host)
    udp_host/port, tcp_host/port, serial_port, baud
    auto_connect  connect by itself at startup (and keep reconnecting). Off =
                  the app starts DISCONNECTED until CONNECT is pressed.

Precedence: once settings were saved from the UI they win over gcs.env's
MAVLINK_CONNECTION; before that, gcs.env / autodetect behave exactly as
before. Changing the link drops the current transport and reconnects on the
new one within ~0.5 s (backend/mavlink/connection.py configure()).
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from app.bridge.settings import app_settings

DEFAULTS = {
    "mode": "auto",
    "udp_role": "udpin",
    "udp_host": "0.0.0.0",
    "udp_port": 14550,
    "tcp_host": "127.0.0.1",
    "tcp_port": 5760,
    "serial_port": "",
    "baud": 57600,
    "auto_connect": True,
}
BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1500000]
_HOST = re.compile(r"^[A-Za-z0-9.\-:_]{1,253}$")


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def load_link_settings() -> tuple[dict, bool]:
    """(config, saved_from_ui)."""
    s = app_settings()
    cfg = dict(DEFAULTS)
    saved = _to_bool(s.value("link/saved", False))
    for key, default in DEFAULTS.items():
        val = s.value(f"link/{key}", default)
        try:
            if isinstance(default, bool):
                cfg[key] = _to_bool(val)
            elif isinstance(default, int):
                cfg[key] = int(val)
            else:
                cfg[key] = str(val)
        except (TypeError, ValueError):
            cfg[key] = default
    return cfg, saved


def save_link_settings(cfg: dict) -> None:
    s = app_settings()
    for key in DEFAULTS:
        s.setValue(f"link/{key}", cfg[key])
    s.setValue("link/saved", True)
    s.sync()


def validate(raw: dict) -> tuple[dict | None, str]:
    cfg = dict(DEFAULTS)
    cfg.update({k: raw[k] for k in DEFAULTS if k in raw and raw[k] is not None})
    cfg["mode"] = str(cfg["mode"]).lower()
    if cfg["mode"] not in ("auto", "udp", "tcp", "serial"):
        return None, "Unknown link type"
    cfg["udp_role"] = "udpout" if str(cfg["udp_role"]).lower() == "udpout" else "udpin"
    cfg["auto_connect"] = _to_bool(cfg["auto_connect"])
    for key in ("udp_host", "tcp_host", "serial_port"):
        cfg[key] = str(cfg[key]).strip()
    for key in ("udp_port", "tcp_port", "baud"):
        try:
            cfg[key] = int(str(cfg[key]).strip())
        except ValueError:
            return None, f"{key.replace('_', ' ').upper()} must be a number"
    if cfg["mode"] == "udp":
        if not _HOST.match(cfg["udp_host"]):
            return None, "Enter a valid UDP host / IP"
        if not 1 <= cfg["udp_port"] <= 65535:
            return None, "UDP port must be 1–65535"
    if cfg["mode"] == "tcp":
        if not _HOST.match(cfg["tcp_host"]):
            return None, "Enter a valid TCP host / IP"
        if not 1 <= cfg["tcp_port"] <= 65535:
            return None, "TCP port must be 1–65535"
    if cfg["mode"] == "serial":
        if not cfg["serial_port"]:
            return None, "Pick a serial port"
        if not 1200 <= cfg["baud"] <= 4000000:
            return None, "Baud rate looks wrong"
    return cfg, ""


def connection_string(cfg: dict) -> str | None:
    mode = cfg["mode"]
    if mode == "udp":
        return f"{cfg['udp_role']}:{cfg['udp_host']}:{cfg['udp_port']}"
    if mode == "tcp":
        return f"tcp:{cfg['tcp_host']}:{cfg['tcp_port']}"
    if mode == "serial":
        return cfg["serial_port"]
    return None          # auto: serial autodetect, then UDP fallback


def apply_at_startup(runtime) -> None:
    """build_source(pre_start=...) hook: runs before the first connect."""
    cfg, saved = load_link_settings()
    conn = runtime.mav_conn
    if saved:
        conn.configure(connection_string(cfg), cfg["baud"] if cfg["mode"] == "serial" else None)
    if not cfg["auto_connect"]:
        conn.set_enabled(False)


def list_serial_ports() -> list[dict]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        desc = p.description if p.description and p.description != "n/a" else ""
        out.append({"device": p.device, "description": desc})
    return out


class LinkController(QObject):
    configChanged = Signal()
    statusChanged = Signal()
    portsChanged = Signal()

    def __init__(self, runtime) -> None:
        super().__init__()
        self._runtime = runtime
        self._cfg, self._saved = load_link_settings()
        self._status = "unavailable" if runtime is None else "connecting"
        self._target = ""
        self._error = ""
        self._attempts = 0
        self._ports: list[dict] = list_serial_ports()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    # ---- status polling (cheap attribute reads) -------------------------------------

    def _poll(self) -> None:
        rt = self._runtime
        if rt is None:
            status, target, error, attempts = "unavailable", "", "No MAVLink backend (simulation or disabled)", 0
        else:
            c = rt.mav_conn
            target = c.active_target or c.describe_target()
            error = c.last_error or ""
            attempts = int(getattr(c, "attempts", 0))
            if not c.enabled:
                status, error = "disconnected", ""
                target = c.describe_target()
            elif c.is_vehicle_alive():
                status, error = "connected", ""
            elif c.master is not None:
                status = "waiting"           # transport open, no vehicle heartbeat yet
            else:
                status = "retrying" if error else "connecting"
        if (status, target, error, attempts) != (self._status, self._target, self._error, self._attempts):
            self._status, self._target, self._error, self._attempts = status, target, error, attempts
            self.statusChanged.emit()

    # ---- QML API --------------------------------------------------------------------

    @Property("QVariantMap", notify=configChanged)
    def config(self) -> dict:
        return dict(self._cfg)

    @Property(bool, notify=configChanged)
    def savedFromUi(self) -> bool:
        return self._saved

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=statusChanged)
    def target(self) -> str:
        return self._target

    @Property(str, notify=statusChanged)
    def error(self) -> str:
        return self._error

    @Property(int, notify=statusChanged)
    def attempts(self) -> int:
        return self._attempts

    @Property(bool, notify=statusChanged)
    def available(self) -> bool:
        return self._runtime is not None

    @Property(bool, notify=statusChanged)
    def enabled(self) -> bool:
        return self._runtime is not None and self._runtime.mav_conn.enabled

    @Property("QVariantList", notify=portsChanged)
    def serialPorts(self) -> list:
        return list(self._ports)

    @Property("QVariantList", constant=True)
    def baudRates(self) -> list:
        return list(BAUDS)

    @Slot()
    def refreshPorts(self) -> None:
        self._ports = list_serial_ports()
        self.portsChanged.emit()

    @Slot("QVariantMap", bool, result="QVariantMap")
    def apply(self, raw: dict, connect_now: bool) -> dict:
        cfg, err = validate(dict(raw or {}))
        if cfg is None:
            return {"ok": False, "error": err}
        relink = (self._runtime is not None and
                  (connection_string(cfg) != connection_string(self._cfg)
                   or (cfg["mode"] == "serial" and cfg["baud"] != self._cfg["baud"])
                   or not self._saved))
        self._cfg, self._saved = cfg, True
        save_link_settings(cfg)
        self.configChanged.emit()
        if self._runtime is not None:
            conn = self._runtime.mav_conn
            if relink:
                conn.configure(connection_string(cfg), cfg["baud"] if cfg["mode"] == "serial" else None)
            if connect_now:
                conn.set_enabled(True)
        self._poll()
        return {"ok": True, "error": ""}

    @Slot()
    def connectLink(self) -> None:
        if self._runtime is not None:
            self._runtime.mav_conn.set_enabled(True)
            self._poll()

    @Slot()
    def disconnectLink(self) -> None:
        if self._runtime is not None:
            self._runtime.mav_conn.set_enabled(False)
            self._poll()

    @Slot("QVariantMap", result=str)
    def preview(self, raw: dict) -> str:
        """Connection string the form would produce (shown under the form)."""
        cfg, err = validate(dict(raw or {}))
        if cfg is None:
            return err
        conn = connection_string(cfg)
        if conn is None:
            return "auto · serial autodetect, then " + os.getenv("MAVLINK_FALLBACK", "udpin:127.0.0.1:14550")
        return f"{conn} @ {cfg['baud']} baud" if cfg["mode"] == "serial" else conn
