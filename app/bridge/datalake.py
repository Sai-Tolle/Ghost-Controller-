"""DataLake — app-wide named-variable store (M3).

Clean-room design inspired by the data-lake concept in Cockpit
(refs/cockpit — AGPL-3.0, concepts only, no code copied): any producer
(telemetry bridge, AI console, vision, user scripts) publishes values under
stable ids ("vehicle/speed"), and any consumer (HUD widgets, future plotters)
reads them or listens for changes. Producers are Python-side; QML consumes
through widget bindings, so the QML layer never imports backend code.

Values are JSON-native (float/int/str/bool). The QML API mirrors the
listener model: DataLake.value(id), DataLake.text(id) and the
valuesChanged group signal re-evaluate widget bindings at a bounded rate.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot


class DataLakeController(QObject):
    """QObject facade over the variable store."""

    valuesChanged = Signal()      # group signal: some id's value changed
    revisionChanged = Signal()    # bumped with valuesChanged for QML bindings

    MAX_LISTENERS = 512

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: dict[str, object] = {}
        self._listeners: dict[str, list] = {}
        self._next_listener = 1
        self._revision = 0
        self._dirty = False
        # QML re-evaluations are cheap but unbounded emit storms still cost;
        # the group signal coalesces at 10 Hz (telemetry cadence).
        self._notify_timer = QTimer(self)
        self._notify_timer.setInterval(100)
        self._notify_timer.timeout.connect(self._flush_notify)
        self._notify_timer.start()

    # ---- Python producer API ------------------------------------------------
    # (also usable from tests without Qt event loop running)

    def set(self, var_id: str, value) -> None:
        self._values[var_id] = value
        self._dirty = True
        for _cb_id, cb in self._listeners.get(var_id, []):
            try:
                cb(var_id, value)
            except Exception:  # noqa: BLE001 — a bad listener must not kill producers
                pass

    def get(self, var_id: str, default=None):
        return self._values.get(var_id, default)

    def listen(self, var_id: str, callback) -> int:
        self._listeners.setdefault(var_id, [])
        if len(self._listeners[var_id]) >= self.MAX_LISTENERS:
            raise RuntimeError("too many listeners for one variable")
        cb_id = self._next_listener
        self._next_listener += 1
        self._listeners[var_id].append((cb_id, callback))
        return cb_id

    def unlisten(self, var_id: str, cb_id: int) -> None:
        lst = self._listeners.get(var_id)
        if lst:
            self._listeners[var_id] = [(i, cb) for (i, cb) in lst if i != cb_id]
            if not self._listeners[var_id]:
                del self._listeners[var_id]

    def snapshot(self) -> dict:
        return dict(self._values)

    def variable_ids(self) -> list[str]:
        return sorted(self._values.keys())

    # ---- QML consumer API ----------------------------------------------------

    @Slot(str, result="QVariant")
    def value(self, var_id: str):  # noqa: N802
        return self._values.get(var_id)

    @Slot(str, result=str)
    def text(self, var_id: str) -> str:  # noqa: N802
        v = self._values.get(var_id)
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.1f}"
        return str(v)

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:  # noqa: N802
        """Monotonic change counter. QML bindings that depend on *any* lake
        value should read `DataLake.revision` inside the binding so the engine
        registers the dependency:
            text: { DataLake.revision; return DataLake.text('vehicle/speed') }
        (Slot calls alone do not create binding dependencies.)"""
        return self._revision

    @Property("QVariantList", notify=valuesChanged)
    def variableIds(self) -> list:  # noqa: N802
        return self.variable_ids()

    @Slot(str, result=bool)
    def exists(self, var_id: str) -> bool:  # noqa: N802
        return var_id in self._values

    # ---- internals ------------------------------------------------------------

    def _flush_notify(self) -> None:
        if self._dirty:
            self._dirty = False
            self._revision += 1
            self.valuesChanged.emit()
            self.revisionChanged.emit()
