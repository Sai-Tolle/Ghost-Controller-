"""Vehicle parameter read / write (MAVLink parameter protocol).

Read all:   PARAM_REQUEST_LIST, then collect PARAM_VALUE. Radios drop packets,
            so once the stream stalls the missing indices are re-requested one
            by one (PARAM_REQUEST_READ by index), a few rounds, like QGC does.
Write:      PARAM_SET, then wait for the vehicle to echo the parameter back in
            a PARAM_VALUE. The echo is the only proof the write landed, so the
            value is compared and the set is retried (3x) when it does not.
Encoding:   MAVLink carries every value in a float32 field. PX4 packs integer
            parameters BYTEWISE (the int's bits sit in the float's bytes);
            ArduPilot C-CASTS (the float holds the numeric value). Getting this
            wrong turns e.g. PX4 SYS_AUTOSTART=4001 into 5.6e-42.

The reader thread hands PARAM_VALUE messages to `handle_message`; every other
method may be called from any thread.
"""
from __future__ import annotations

import math
import re
import struct
import threading
import time
from typing import Callable, Optional

from pymavlink import mavutil

M = mavutil.mavlink

# MAV_PARAM_TYPE -> (struct code, is_integer, label)
_TYPES = {
    M.MAV_PARAM_TYPE_UINT8: ("<B", True, "UINT8"),
    M.MAV_PARAM_TYPE_INT8: ("<b", True, "INT8"),
    M.MAV_PARAM_TYPE_UINT16: ("<H", True, "UINT16"),
    M.MAV_PARAM_TYPE_INT16: ("<h", True, "INT16"),
    M.MAV_PARAM_TYPE_UINT32: ("<I", True, "UINT32"),
    M.MAV_PARAM_TYPE_INT32: ("<i", True, "INT32"),
    M.MAV_PARAM_TYPE_REAL32: ("<f", False, "FLOAT"),
}
_INT_RANGES = {
    "<B": (0, 0xFF), "<b": (-0x80, 0x7F), "<H": (0, 0xFFFF), "<h": (-0x8000, 0x7FFF),
    "<I": (0, 0xFFFFFFFF), "<i": (-0x80000000, 0x7FFFFFFF),
}


def type_label(ptype: int) -> str:
    return _TYPES.get(ptype, ("<f", False, f"T{ptype}"))[2]


def is_integer_type(ptype: int) -> bool:
    return _TYPES.get(ptype, ("<f", False, ""))[1]


def decode_value(raw: float, ptype: int, bytewise: bool):
    """PARAM_VALUE.param_value -> Python int/float."""
    code, is_int, _ = _TYPES.get(ptype, ("<f", False, ""))
    if not is_int:
        return float(raw)
    if not bytewise:
        return int(round(raw))
    buf = struct.pack("<f", raw)
    size = struct.calcsize(code)
    return struct.unpack(code, buf[:size])[0]


def encode_value(value, ptype: int, bytewise: bool) -> float:
    """Python value -> float32 field for PARAM_SET. Raises ValueError."""
    code, is_int, _ = _TYPES.get(ptype, ("<f", False, ""))
    if not is_int:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("value must be a finite number")
        return v
    fv = float(value)
    if fv != int(fv):
        raise ValueError("this parameter takes a whole number")
    iv = int(fv)
    lo, hi = _INT_RANGES[code]
    if not lo <= iv <= hi:
        raise ValueError(f"out of range for {type_label(ptype)} ({lo} … {hi})")
    if not bytewise:
        return float(iv)
    size = struct.calcsize(code)
    buf = struct.pack(code, iv) + b"\x00" * (4 - size)
    return struct.unpack("<f", buf)[0]


def values_equal(a, b, ptype: int) -> bool:
    if is_integer_type(ptype):
        return int(a) == int(b)
    fa = struct.unpack("<f", struct.pack("<f", float(a)))[0]
    fb = struct.unpack("<f", struct.pack("<f", float(b)))[0]
    return fa == fb or abs(fa - fb) <= 1e-6 * max(1.0, abs(fa), abs(fb))


def format_value(value, ptype: int) -> str:
    if is_integer_type(ptype):
        return str(int(value))
    v = float(value)
    if v == int(v) and abs(v) < 1e7:
        return f"{v:.1f}"
    return f"{v:.7g}"


# ---------------------------------------------------------------- files

def export_text(params: dict, sysid: int = 1, compid: int = 1) -> str:
    """QGroundControl .params format (also read by Mission Planner)."""
    lines = ["# Onboard parameters for Vehicle %d" % sysid, "#",
             "# Stack: Ghost Handler GCS", "#",
             "# Vehicle-Id Component-Id Name Value Type"]
    for name in sorted(params):
        p = params[name]
        lines.append(f"{sysid}\t{compid}\t{name}\t{format_value(p['value'], p['type'])}\t{p['type']}")
    return "\n".join(lines) + "\n"


_SPLIT = re.compile(r"[,\t ]+")


def parse_text(text: str) -> dict:
    """Read QGC (.params, 5 columns), Mission Planner (NAME,VALUE) and
    MAVProxy (NAME VALUE) files. Returns {name: float}."""
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in _SPLIT.split(line) if p]
        try:
            if len(parts) >= 5 and parts[0].isdigit() and parts[1].isdigit():
                name, value = parts[2], float(parts[3])
            elif len(parts) >= 2:
                name, value = parts[0], float(parts[1])
            else:
                continue
        except ValueError:
            continue
        if re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            out[name] = value
    return out


# ---------------------------------------------------------------- manager

class ParamManager:
    STALL_S = 1.0          # no PARAM_VALUE for this long -> re-request missing
    MAX_ROUNDS = 6         # missing-index rounds before giving up
    SET_TIMEOUT_S = 1.5
    SET_RETRIES = 3

    def __init__(self, mav_conn, is_armed: Optional[Callable[[], bool]] = None) -> None:
        self.mav_conn = mav_conn
        self._cond = threading.Condition()
        self._params: dict[str, dict] = {}
        self._index: dict[int, str] = {}
        self._total = 0
        self._state = "idle"           # idle | loading | ready | partial | error
        self._message = ""
        self._version = 0
        self._last_rx = 0.0
        self._echo: dict[str, tuple] = {}     # name -> (monotonic, value) of last PARAM_VALUE
        self._load_token = 0
        self._target = (0, 0)
        self.is_armed = is_armed or (lambda: False)

    # ---- helpers ---------------------------------------------------------

    def _bytewise(self) -> bool:
        return (self.mav_conn.get_autopilot() or "") == "PX4"

    def _master(self):
        return self.mav_conn.get_master()

    def _bump(self) -> None:
        self._version += 1
        self._cond.notify_all()

    # ---- reader-thread entry --------------------------------------------

    def handle_message(self, msg) -> None:
        if msg.get_type() != "PARAM_VALUE":
            return
        master = self._master()
        if master is not None:
            comp = int(getattr(master, "target_component", 0) or 0)
            if comp and msg.get_srcComponent() != comp:
                return            # camera / gimbal component parameters
        name = msg.param_id
        if isinstance(name, (bytes, bytearray)):
            name = name.decode("ascii", "ignore")
        name = name.rstrip("\x00").strip()
        if not name:
            return
        ptype = int(msg.param_type)
        value = decode_value(msg.param_value, ptype, self._bytewise())
        with self._cond:
            self._params[name] = {"value": value, "type": ptype,
                                  "index": int(msg.param_index)}
            if 0 <= msg.param_index < 65535:
                self._index[int(msg.param_index)] = name
            if 0 < msg.param_count < 65535:
                self._total = int(msg.param_count)
            self._echo[name] = (time.monotonic(), value)
            self._last_rx = time.monotonic()
            self._bump()

    # ---- state -------------------------------------------------------------

    def reset(self) -> None:
        """New vehicle / new link: the cached set belongs to the old one."""
        with self._cond:
            self._load_token += 1
            self._params.clear()
            self._index.clear()
            self._echo.clear()
            self._total = 0
            self._state = "idle"
            self._message = ""
            self._bump()

    def snapshot(self) -> dict:
        with self._cond:
            return {
                "version": self._version,
                "state": self._state,
                "message": self._message,
                "received": len(self._index) if self._total else len(self._params),
                "total": self._total,
                "params": {k: dict(v) for k, v in self._params.items()},
            }

    def version(self) -> int:
        return self._version

    # ---- read all ----------------------------------------------------------

    def request_all(self) -> bool:
        """Start a full download in the background. False = no vehicle."""
        master = self._master()
        if master is None:
            with self._cond:
                self._state, self._message = "error", "No vehicle link"
                self._bump()
            return False
        with self._cond:
            self._load_token += 1
            token = self._load_token
            self._params.clear()
            self._index.clear()
            self._total = 0
            self._state, self._message = "loading", "Requesting parameter list…"
            self._last_rx = time.monotonic()
            self._bump()
        threading.Thread(target=self._load, args=(token,), daemon=True, name="param-load").start()
        return True

    def _send_list(self) -> bool:
        m = self._master()
        if m is None:
            return False
        return self.mav_conn.send_mavlink("param_request_list_send", m.target_system, m.target_component)

    def _send_read_index(self, idx: int) -> bool:
        m = self._master()
        if m is None:
            return False
        return self.mav_conn.send_mavlink("param_request_read_send", m.target_system,
                                          m.target_component, b"", int(idx))

    def _send_read_name(self, name: str) -> bool:
        m = self._master()
        if m is None:
            return False
        return self.mav_conn.send_mavlink("param_request_read_send", m.target_system,
                                          m.target_component, name.encode("ascii"), -1)

    def _load(self, token: int) -> None:
        if not self._send_list():
            self._finish(token, "error", "No vehicle link")
            return
        rounds = 0
        started = time.monotonic()
        while True:
            with self._cond:
                if token != self._load_token:
                    return
                self._cond.wait(0.25)
                if token != self._load_token:
                    return
                total, have = self._total, len(self._index)
                stalled = time.monotonic() - self._last_rx > self.STALL_S
                if total:
                    self._message = f"Loading {have}/{total}"
                if total and have >= total:
                    break
            if self._master() is None:
                self._finish(token, "error", "Link lost while loading")
                return
            if not stalled:
                if time.monotonic() - started > 180:
                    break
                continue
            if total == 0:
                # Nothing at all yet: the list request itself was lost.
                rounds += 1
                if rounds > 3:
                    self._finish(token, "error", "Vehicle did not answer the parameter request")
                    return
                self._send_list()
                with self._cond:
                    self._last_rx = time.monotonic()
                continue
            rounds += 1
            if rounds > self.MAX_ROUNDS:
                break
            with self._cond:
                missing = [i for i in range(total) if i not in self._index]
                self._last_rx = time.monotonic()
            for i in missing[:60]:          # bounded burst, radios are slow
                self._send_read_index(i)
                time.sleep(0.004)
        with self._cond:
            total, have = self._total, len(self._index)
        if total and have >= total:
            self._finish(token, "ready", f"{have} parameters")
        else:
            self._finish(token, "partial", f"Loaded {have} of {total} — some parameters did not arrive")

    def _finish(self, token: int, state: str, message: str) -> None:
        with self._cond:
            if token != self._load_token:
                return
            self._state, self._message = state, message
            self._bump()

    # ---- single read / write ----------------------------------------------

    def refresh(self, name: str) -> bool:
        return self._send_read_name(name)

    def set_param(self, name: str, value) -> dict:
        """Blocking write with echo verification. Returns
        {"ok": bool, "value": confirmed value or None, "error": str}."""
        if self.is_armed():
            return {"ok": False, "value": None, "error": "Vehicle is armed — disarm to write parameters"}
        with self._cond:
            current = self._params.get(name)
        if current is None:
            return {"ok": False, "value": None, "error": "Unknown parameter (not on this vehicle)"}
        ptype = current["type"]
        try:
            wire = encode_value(value, ptype, self._bytewise())
        except (TypeError, ValueError) as exc:
            return {"ok": False, "value": None, "error": str(exc)}
        target = decode_value(wire, ptype, self._bytewise())
        last_seen = None
        for _attempt in range(self.SET_RETRIES):
            master = self._master()
            if master is None:
                return {"ok": False, "value": None, "error": "No vehicle link"}
            sent_at = time.monotonic()
            if not self.mav_conn.send_mavlink("param_set_send", master.target_system,
                                              master.target_component, name.encode("ascii"),
                                              wire, ptype):
                return {"ok": False, "value": None, "error": "Send failed"}
            deadline = sent_at + self.SET_TIMEOUT_S
            with self._cond:
                while True:
                    echo = self._echo.get(name)
                    if echo and echo[0] >= sent_at:
                        last_seen = echo[1]
                        if values_equal(echo[1], target, ptype):
                            return {"ok": True, "value": echo[1], "error": ""}
                        break       # vehicle answered with something else: retry
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self._cond.wait(left)
        if last_seen is not None:
            return {"ok": False, "value": last_seen,
                    "error": f"Vehicle kept {format_value(last_seen, ptype)} (rejected or clamped)"}
        return {"ok": False, "value": None, "error": "No confirmation from vehicle"}

    def fetch(self, names, timeout: float = 2.5) -> dict:
        """Read specific parameters by name (no full download needed).
        Returns {name: {"value", "type"}} for the ones the vehicle has;
        names the vehicle does not know simply never answer."""
        names = [n for n in dict.fromkeys(names) if n]
        if self._master() is None or not names:
            return {}
        started = time.monotonic()
        for attempt in range(2):
            with self._cond:
                missing = [n for n in names if not (n in self._echo and self._echo[n][0] >= started)]
            if not missing:
                break
            for n in missing:
                self._send_read_name(n)
                time.sleep(0.003)
            deadline = time.monotonic() + timeout / 2
            with self._cond:
                while time.monotonic() < deadline:
                    if all(n in self._echo and self._echo[n][0] >= started for n in names):
                        break
                    self._cond.wait(0.1)
        with self._cond:
            return {n: {"value": self._params[n]["value"], "type": self._params[n]["type"]}
                    for n in names
                    if n in self._params and n in self._echo and self._echo[n][0] >= started}
