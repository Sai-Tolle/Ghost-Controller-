"""Operator-configurable battery policy shared by the telemetry, health,
preflight and command-guard code.

The desktop app (or any other front end) configures it once via `configure()`;
every module that cares about "how full is the battery / is it low" reads the
same singleton, so the HUD, the failsafe, the pre-arm check and the guard can
never disagree about thresholds.

`estimator` is an optional callable `pack_voltage_v -> percent | None`. When set
(voltage mode) it REPLACES the vehicle-reported remaining %, which many
airframes report badly (no current sensor, wrong capacity, fixed 100 %)."""
from __future__ import annotations

import threading
from typing import Callable, Optional

DEFAULT_WARN_PCT = 25
DEFAULT_CRIT_PCT = 15


class BatteryPolicy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.warn_pct: float = DEFAULT_WARN_PCT
        self.crit_pct: float = DEFAULT_CRIT_PCT
        self._estimator: Optional[Callable[[float], Optional[float]]] = None

    def configure(self, warn_pct: float, crit_pct: float,
                  estimator: Optional[Callable[[float], Optional[float]]] = None) -> None:
        with self._lock:
            self.warn_pct = float(warn_pct)
            self.crit_pct = float(crit_pct)
            self._estimator = estimator

    def reset(self) -> None:
        self.configure(DEFAULT_WARN_PCT, DEFAULT_CRIT_PCT, None)

    @property
    def uses_voltage(self) -> bool:
        return self._estimator is not None

    def remaining(self, vehicle_remaining, voltage) -> Optional[float]:
        """Percent remaining under the active policy (None = unknown)."""
        est = self._estimator
        if est is not None and voltage and voltage > 1.0:
            try:
                value = est(float(voltage))
            except Exception:  # noqa: BLE001 — a bad estimator must never kill telemetry
                value = None
            if value is not None:
                return float(value)
        if vehicle_remaining is None or vehicle_remaining < 0:
            return None
        return float(vehicle_remaining)


battery_policy = BatteryPolicy()
