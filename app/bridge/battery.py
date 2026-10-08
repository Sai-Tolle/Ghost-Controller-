"""Operator-configurable battery model.

Why: the vehicle's own "remaining %" is frequently wrong (no current sensor, a
wrong capacity parameter, a fixed 100 %). The operator can tell the GCS what pack
is fitted (cell count + chemistry + usable voltage window) and have the
percentage estimated from the measured PACK VOLTAGE instead, with warn/critical
thresholds of their choosing. The same profile is pushed to the backend so the
failsafe, pre-arm check and command guard use identical numbers.

Voltage-based estimates are open-circuit curves smoothed over time; real packs
sag under load, so the estimate reads pessimistic during hard climbs and
recovers in hover. It is an estimate, not a coulomb counter.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, asdict

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from app.bridge.settings import app_settings

# Normalised LiPo open-circuit curve: (fraction of the usable window, percent).
# Derived from a typical per-cell table 4.20 V=100 % … 3.27 V=0 %.
_LIPO_V = [3.27, 3.61, 3.69, 3.71, 3.73, 3.75, 3.77, 3.79, 3.80, 3.82, 3.84, 3.85,
           3.87, 3.91, 3.95, 3.98, 4.02, 4.08, 4.11, 4.15, 4.20]
_LIPO_P = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]
_LIPO_X = [(v - 3.27) / (4.20 - 3.27) for v in _LIPO_V]

PRESETS = {
    "lipo":  {"label": "LiPo",   "full_v": 4.20, "empty_v": 3.50, "curve": "lipo"},
    "lihv":  {"label": "LiHV",   "full_v": 4.35, "empty_v": 3.50, "curve": "lipo"},
    "liion": {"label": "Li-ion", "full_v": 4.20, "empty_v": 3.00, "curve": "linear"},
}
DEFAULTS = {"source": "vehicle", "cells": 0, "chemistry": "lipo",
            "full_v": 4.20, "empty_v": 3.50, "warn_pct": 30, "crit_pct": 15, "capacity_mah": 0}
EMA_ALPHA = 0.04          # at 10 Hz: ~2.5 s time constant


@dataclass
class BatteryProfile:
    source: str = "vehicle"        # "vehicle" | "voltage"
    cells: int = 0                 # series count (S); 0 = not set
    chemistry: str = "lipo"        # lipo | lihv | liion | custom
    full_v: float = 4.20           # per-cell voltage that means 100 %
    empty_v: float = 3.50          # per-cell voltage that means 0 %
    warn_pct: float = 30
    crit_pct: float = 15
    capacity_mah: int = 0          # pack capacity; 0 = not set

    @property
    def curve(self) -> str:
        return PRESETS.get(self.chemistry, {"curve": "lipo"})["curve"]


def percent_for_cell_voltage(v_cell: float, p: BatteryProfile) -> float:
    """Pure open-circuit estimate, 0..100, rescaled to the operator's window."""
    span = p.full_v - p.empty_v
    if span <= 0:
        return 0.0
    x = (v_cell - p.empty_v) / span
    x = max(0.0, min(1.0, x))
    if p.curve == "linear":
        return round(x * 100.0, 1)
    # piecewise-linear interpolation on the normalised LiPo curve
    for i in range(1, len(_LIPO_X)):
        if x <= _LIPO_X[i]:
            x0, x1 = _LIPO_X[i - 1], _LIPO_X[i]
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return round(_LIPO_P[i - 1] + t * (_LIPO_P[i] - _LIPO_P[i - 1]), 1)
    return 100.0


def validate(raw: dict, current: BatteryProfile) -> tuple[BatteryProfile | None, str]:
    """Return (profile, "") or (None, human-readable error)."""
    try:
        source = str(raw.get("source", current.source))
        chemistry = str(raw.get("chemistry", current.chemistry))
        cells = int(float(raw.get("cells", current.cells)))
        full_v = float(raw.get("full_v", current.full_v))
        empty_v = float(raw.get("empty_v", current.empty_v))
        warn = float(raw.get("warn_pct", current.warn_pct))
        crit = float(raw.get("crit_pct", current.crit_pct))
        cap_raw = raw.get("capacity_mah", current.capacity_mah)
        capacity = int(float(cap_raw)) if str(cap_raw).strip() not in ("", "None") else 0
    except (TypeError, ValueError):
        return None, "All fields must be numbers."
    if source not in ("vehicle", "voltage"):
        return None, "Unknown battery source."
    if chemistry not in ("lipo", "lihv", "liion", "custom"):
        return None, "Unknown chemistry."
    if not (0 <= cells <= 14):
        return None, "Cells must be between 1 and 14."
    if source == "voltage" and cells < 1:
        return None, "Set the cell count (S) to use voltage-based readings."
    if not (3.3 <= full_v <= 4.5):
        return None, "Full voltage per cell must be 3.3–4.5 V."
    if not (2.4 <= empty_v <= full_v - 0.2):
        return None, "Empty voltage per cell must be 2.4 V and at least 0.2 V below full."
    if not (2 <= warn <= 99):
        return None, "Warning level must be 2–99 %."
    if not (1 <= crit < warn):
        return None, "Critical level must be at least 1 % and below the warning level."
    if any(map(math.isnan, (full_v, empty_v, warn, crit))):
        return None, "Values must be real numbers."
    if capacity != 0 and not (100 <= capacity <= 200000):
        return None, "Capacity must be 100–200000 mAh (or 0 = not set)."
    return BatteryProfile(source, cells, chemistry, full_v, empty_v, warn, crit, capacity), ""


def cell_voltage_for_percent(pct: float, p: BatteryProfile) -> float:
    """Inverse of percent_for_cell_voltage (per-cell volts for a % level)."""
    pct = max(0.0, min(100.0, float(pct)))
    span = p.full_v - p.empty_v
    if p.curve == "linear":
        x = pct / 100.0
    else:
        x = 1.0
        for i in range(1, len(_LIPO_P)):
            if pct <= _LIPO_P[i]:
                t = (pct - _LIPO_P[i - 1]) / (_LIPO_P[i] - _LIPO_P[i - 1])
                x = _LIPO_X[i - 1] + t * (_LIPO_X[i] - _LIPO_X[i - 1])
                break
    return p.empty_v + x * span


# ---- flight-controller battery parameters ------------------------------------------
# The GCS-side profile only fixes what the GCS SHOWS. Writing the matching
# firmware parameters makes the flight controller's own %, warnings and
# failsafes agree with it.
PX4_NAMES = ["BAT1_N_CELLS", "BAT1_V_CHARGED", "BAT1_V_EMPTY", "BAT1_CAPACITY",
             "BAT_N_CELLS", "BAT_V_CHARGED", "BAT_V_EMPTY", "BAT_CAPACITY",     # PX4 < 1.13
             "BAT_LOW_THR", "BAT_CRIT_THR", "BAT_EMERGEN_THR"]
ARDU_NAMES = ["BATT_CAPACITY", "BATT_LOW_VOLT", "BATT_CRT_VOLT", "BATT_LOW_MAH", "BATT_CRT_MAH"]


def vehicle_plan(p: BatteryProfile, autopilot: str, current: dict) -> list[dict]:
    """Rows {name, current, target, change, note} for params the vehicle HAS.
    `current` = {name: {"value", "type"}} as read from the vehicle."""
    want: list[tuple[str, float, str]] = []
    if autopilot == "PX4":
        pre = "BAT1_" if any(n.startswith("BAT1_") for n in current) else "BAT_"
        if p.cells >= 1:
            want.append((pre + "N_CELLS", p.cells, "cell count"))
        # PX4 defines both UNDER LOAD ("never the nominal 4.2 V" — PX4 docs):
        # resting full 4.20 -> 4.05 (PX4 default), LiHV 4.35 -> 4.20.
        want.append((pre + "V_CHARGED", round(p.full_v - 0.15, 3), "full V/cell under load"))
        want.append((pre + "V_EMPTY", round(p.empty_v, 3), "empty V/cell under load"))
        if p.capacity_mah > 0:
            want.append((pre + "CAPACITY", float(p.capacity_mah), "capacity mAh"))
        emerg = float(current.get("BAT_EMERGEN_THR", {}).get("value", 0.05))
        crit = min(0.25, max(0.05, p.crit_pct / 100.0, emerg + 0.01))   # PX4 allowed ranges
        low = min(0.5, max(0.12, p.warn_pct / 100.0, crit + 0.01))
        want.append(("BAT_LOW_THR", round(low, 2), "low warning"))
        want.append(("BAT_CRIT_THR", round(crit, 2), "critical"))
    elif autopilot == "ArduPilot":
        if p.capacity_mah > 0:
            want.append(("BATT_CAPACITY", float(p.capacity_mah), "capacity mAh"))
            want.append(("BATT_LOW_MAH", float(round(p.capacity_mah * p.warn_pct / 100.0)), "low failsafe mAh left"))
            want.append(("BATT_CRT_MAH", float(round(p.capacity_mah * p.crit_pct / 100.0)), "critical failsafe mAh left"))
        if p.cells >= 1:
            # ArduPilot compares these with the SAGGING in-flight voltage, so
            # they follow the empty cell voltage (wiki: LiPo 3.5 / 3.3 V per
            # cell), not the resting %-curve (which would fail-safe in climbs).
            want.append(("BATT_LOW_VOLT", round(p.cells * p.empty_v, 2), "low failsafe V (under load)"))
            want.append(("BATT_CRT_VOLT", round(p.cells * max(2.5, p.empty_v - 0.2), 2), "critical failsafe V"))
    rows = []
    for name, target, note in want:
        cur = current.get(name)
        if cur is None:
            continue
        is_int = cur["type"] not in (9, 10)       # MAV_PARAM_TYPE_REAL32/64
        tgt = int(round(target)) if is_int else float(target)
        change = (int(cur["value"]) != tgt) if is_int else abs(float(cur["value"]) - tgt) > 1e-4
        fmt = (lambda v: str(int(v))) if is_int else (lambda v: f"{float(v):.3g}" if abs(float(v)) < 10 else f"{float(v):.6g}")
        rows.append({"name": name, "current": fmt(cur["value"]), "target": fmt(tgt), "value": tgt,
                     "change": bool(change), "note": note, "status": "", "ok": False})
    return rows


class BatteryController(QObject):
    """QML: `Battery` context property. Persisted in QSettings (battery/*)."""

    profileChanged = Signal()
    vehicleSyncChanged = Signal()

    def __init__(self, runtime=None, parent=None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._settings = app_settings()
        self._profile = self._load()
        self._ema: float | None = None
        self._push_to_backend()
        # vehicle-parameter sync (worker thread writes _sync_next, timer publishes)
        self._sync = {"state": "idle", "message": "", "rows": [], "autopilot": ""}
        self._sync_lock = threading.Lock()
        self._sync_next: dict | None = None
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(100)
        self._sync_timer.timeout.connect(self._publish_sync)
        self._sync_timer.start()

    # ---- persistence ---------------------------------------------------------
    def _load(self) -> BatteryProfile:
        s = self._settings
        raw = {k: s.value(f"battery/{k}", v) for k, v in DEFAULTS.items()}
        prof, _ = validate(raw, BatteryProfile())
        return prof or BatteryProfile()

    def _save(self) -> None:
        for k, v in asdict(self._profile).items():
            self._settings.setValue(f"battery/{k}", v)
        self._settings.sync()

    # ---- QML API ---------------------------------------------------------------
    @Property("QVariantMap", notify=profileChanged)
    def profile(self) -> dict:  # noqa: N802
        return asdict(self._profile)

    @Property("QVariantList", constant=True)
    def presets(self) -> list:  # noqa: N802
        return [{"id": k, **v} for k, v in PRESETS.items()]

    @Property(float, notify=profileChanged)
    def warnPct(self) -> float:  # noqa: N802
        return float(self._profile.warn_pct)

    @Property(float, notify=profileChanged)
    def critPct(self) -> float:  # noqa: N802
        return float(self._profile.crit_pct)

    @Slot("QVariantMap", result="QVariantMap")
    def apply(self, raw: dict) -> dict:  # noqa: A003
        prof, err = validate(dict(raw), self._profile)
        if prof is None:
            return {"ok": False, "error": err}
        self._profile = prof
        self._ema = None
        self._save()
        self._push_to_backend()
        self.profileChanged.emit()
        return {"ok": True, "error": ""}

    @Slot(result="QVariantMap")
    def resetDefaults(self) -> dict:  # noqa: N802
        return self.apply(dict(DEFAULTS))

    @Slot(float, float, result=int)
    def detectCells(self, pack_v: float, full_v: float) -> int:  # noqa: N802
        """Cell count from a FULLY CHARGED pack voltage (ambiguous otherwise)."""
        if pack_v < 3.0 or full_v <= 0:
            return 0
        return max(1, min(14, math.ceil(pack_v / full_v - 0.02)))

    # ---- write the pack to the flight controller ------------------------------------
    def _set_sync(self, **kw) -> None:
        with self._sync_lock:
            base = dict(self._sync_next or self._sync)
            base.update(kw)
            self._sync_next = base

    def _publish_sync(self) -> None:
        with self._sync_lock:
            nxt, self._sync_next = self._sync_next, None
        if nxt is not None:
            self._sync = nxt
            self.vehicleSyncChanged.emit()

    @Property("QVariantMap", notify=vehicleSyncChanged)
    def vehicleSync(self) -> dict:  # noqa: N802
        return dict(self._sync)

    @Property(bool, constant=True)
    def canSyncVehicle(self) -> bool:  # noqa: N802
        return self._runtime is not None and hasattr(self._runtime, "params")

    @Slot()
    def prepareVehicleSync(self) -> None:  # noqa: N802
        """Read the vehicle's battery params and build a preview (nothing is written)."""
        rt = self._runtime
        if rt is None or not hasattr(rt, "params"):
            self._set_sync(state="error", message="No MAVLink backend", rows=[])
            return
        if not rt.mav_conn.is_vehicle_alive():
            self._set_sync(state="error", message="No vehicle link", rows=[])
            return
        autopilot = rt.mav_conn.get_autopilot() or ""
        if autopilot not in ("PX4", "ArduPilot"):
            self._set_sync(state="error", message=f"Unsupported autopilot ({autopilot or 'unknown'})", rows=[])
            return
        self._set_sync(state="reading", message="Reading battery parameters…", rows=[], autopilot=autopilot)
        profile = self._profile

        def run() -> None:
            names = PX4_NAMES if autopilot == "PX4" else ARDU_NAMES
            current = rt.params.fetch(names)
            rows = vehicle_plan(profile, autopilot, current)
            if not rows:
                self._set_sync(state="error", rows=[],
                               message="Vehicle did not report its battery parameters" if not current
                               else "Set cells and/or capacity first — nothing to write")
                return
            n = sum(1 for r in rows if r["change"])
            self._set_sync(state="preview", rows=rows,
                           message=f"{n} change(s) for {autopilot}" if n else "Vehicle already matches this pack")

        threading.Thread(target=run, daemon=True, name="battery-sync-read").start()

    @Slot()
    def confirmVehicleSync(self) -> None:  # noqa: N802
        rt = self._runtime
        if self._sync.get("state") != "preview" or rt is None:
            return
        rows = [dict(r) for r in self._sync.get("rows", [])]
        self._set_sync(state="writing", message="Writing…")

        def run() -> None:
            ok = total = 0
            for r in rows:
                if not r["change"]:
                    continue
                total += 1
                res = rt.params.set_param(r["name"], r["value"])
                r["ok"] = bool(res.get("ok"))
                r["status"] = "✓" if r["ok"] else res.get("error", "failed")
                if r["ok"]:
                    ok += 1
                    r["current"] = r["target"]
                self._set_sync(rows=[dict(x) for x in rows])
            self._set_sync(state="done" if ok == total else "error", rows=rows,
                           message=(f"{ok}/{total} written and confirmed by the vehicle"
                                    + ("" if ok == total else " — see rows")))

        threading.Thread(target=run, daemon=True, name="battery-sync-write").start()

    @Slot()
    def cancelVehicleSync(self) -> None:  # noqa: N802
        if self._sync.get("state") in ("reading", "writing"):
            return
        self._set_sync(state="idle", message="", rows=[])

    # ---- model ----------------------------------------------------------------------
    def estimate(self, pack_v: float) -> float | None:
        """Stateless estimate for the BACKEND (failsafe / pre-arm / guard)."""
        p = self._profile
        if p.source != "voltage" or p.cells < 1 or pack_v < 1.0:
            return None
        return percent_for_cell_voltage(pack_v / p.cells, p)

    def apply_to_frame(self, frame: dict) -> dict:
        """Rewrite battery fields of a normalised frame under the active profile."""
        p = self._profile
        out = dict(frame)
        raw_extra = (frame.get("extra") or {}).get("battery") or {}
        vehicle_pct = raw_extra.get("remaining_vehicle", frame.get("battery_pct", -1.0))
        vehicle_pct = -1.0 if vehicle_pct is None else float(vehicle_pct)
        pack_v = float(frame.get("battery_v") or 0.0)
        out["battery_pct_vehicle"] = vehicle_pct
        out["battery_warn"] = float(p.warn_pct)
        out["battery_crit"] = float(p.crit_pct)
        out["battery_cell_v"] = round(pack_v / p.cells, 3) if p.cells >= 1 and pack_v > 1.0 else None
        out["battery_source"] = "vehicle"
        if frame.get("connected") and p.source == "voltage" and p.cells >= 1 and pack_v > 1.0:
            raw = percent_for_cell_voltage(pack_v / p.cells, p)
            self._ema = raw if self._ema is None or abs(raw - self._ema) > 25 \
                else self._ema + EMA_ALPHA * (raw - self._ema)
            out["battery_pct"] = round(self._ema, 1)
            out["battery_source"] = "voltage"
        else:
            self._ema = None
            out["battery_pct"] = vehicle_pct
        return out

    def _push_to_backend(self) -> None:
        """Mirror warn/critical (+ estimator) into the backend's shared policy."""
        try:
            from mavlink.battery_policy import battery_policy
        except ImportError:        # backend not attached (simulation / tests)
            return
        p = self._profile
        battery_policy.configure(
            p.warn_pct, p.crit_pct,
            self.estimate if (p.source == "voltage" and p.cells >= 1) else None)
