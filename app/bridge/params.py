"""ParamController: the PARAMETERS window's view of backend/mavlink/params.py.

Edits are STAGED first (shown as pending, nothing is sent), then WRITE sends
them one by one and only clears an edit once the vehicle echoed the new value
back. Anything the vehicle rejected or clamped stays staged with the reason.
Writes are refused while the vehicle is armed.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex, QObject,
                            Property, QTimer, QUrl, Qt, Signal, Slot)


def _backend_params():
    # backend/ is put on sys.path by BackendRuntime; tests add it themselves.
    from mavlink import params as P
    return P


def _group_of(name: str) -> str:
    """Prefix before the first "_", instance digits dropped so PX4 BAT1_* /
    BAT2_* sit with BAT_* and SER_TEL1 with SER_."""
    head, sep, _ = name.partition("_")
    if not (sep and head):
        return "MISC"
    stripped = head.rstrip("0123456789")
    return stripped or head


def _local_path(url_or_path: str) -> Path:
    u = QUrl(url_or_path)
    if u.isLocalFile():
        return Path(u.toLocalFile())
    return Path(url_or_path)


class ParamListModel(QAbstractListModel):
    NameRole = Qt.UserRole + 1
    ValueRole = Qt.UserRole + 2
    TypeRole = Qt.UserRole + 3
    PendingRole = Qt.UserRole + 4
    ModifiedRole = Qt.UserRole + 5
    ErrorRole = Qt.UserRole + 6
    IntegerRole = Qt.UserRole + 7

    def __init__(self, ctl: "ParamController") -> None:
        super().__init__()
        self._ctl = ctl
        self._rows: list[str] = []

    def roleNames(self):
        return {
            self.NameRole: QByteArray(b"name"), self.ValueRole: QByteArray(b"value"),
            self.TypeRole: QByteArray(b"ptype"), self.PendingRole: QByteArray(b"pending"),
            self.ModifiedRole: QByteArray(b"modified"), self.ErrorRole: QByteArray(b"error"),
            self.IntegerRole: QByteArray(b"integer"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._rows[index.row()]
        return self._ctl._role_value(name, role)

    def set_rows(self, rows: list[str]) -> None:
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def touch(self, names) -> None:
        names = set(names)
        for i, n in enumerate(self._rows):
            if n in names:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)

    def rows(self) -> list[str]:
        return self._rows


class ParamController(QObject):
    stateChanged = Signal()
    viewChanged = Signal()
    pendingChanged = Signal()
    writeChanged = Signal()

    def __init__(self, runtime) -> None:
        super().__init__()
        self._runtime = runtime
        self._mgr = getattr(runtime, "params", None)
        self._P = _backend_params() if self._mgr is not None else None
        self._model = ParamListModel(self)
        self._params: dict[str, dict] = {}
        self._version = -1
        self._state, self._message, self._received, self._total = "idle", "", 0, 0
        self._pending: dict[str, object] = {}
        self._errors: dict[str, str] = {}
        self._filter = ""
        self._group = ""
        self._modified_only = False
        self._groups: list[dict] = []
        self._writing = False
        self._write_done = 0
        self._write_total = 0
        self._write_ok = 0
        self._results: list[tuple[str, dict]] = []
        self._results_lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---- model plumbing -------------------------------------------------------------

    def _role_value(self, name: str, role: int):
        p = self._params.get(name)
        M = ParamListModel
        if role == M.NameRole:
            return name
        if p is None:
            return ""
        if role == M.ValueRole:
            return self._P.format_value(p["value"], p["type"])
        if role == M.TypeRole:
            return self._P.type_label(p["type"])
        if role == M.PendingRole:
            v = self._pending.get(name)
            return "" if v is None else self._P.format_value(v, p["type"])
        if role == M.ModifiedRole:
            return name in self._pending
        if role == M.ErrorRole:
            return self._errors.get(name, "")
        if role == M.IntegerRole:
            return self._P.is_integer_type(p["type"])
        return None

    def _rebuild_rows(self) -> None:
        f = self._filter.upper()
        rows = []
        for name in sorted(self._params):
            if self._group and _group_of(name) != self._group:
                continue
            if f and f not in name.upper():
                continue
            if self._modified_only and name not in self._pending:
                continue
            rows.append(name)
        self._model.set_rows(rows)

    def _rebuild_groups(self) -> None:
        counts: dict[str, int] = {}
        for name in self._params:
            g = _group_of(name)
            counts[g] = counts.get(g, 0) + 1
        self._groups = [{"name": g, "count": counts[g]} for g in sorted(counts)]

    def _poll(self) -> None:
        self._apply_write_results()
        if self._mgr is None:
            return
        if self._mgr.version() == self._version:
            return
        snap = self._mgr.snapshot()
        self._version = snap["version"]
        new = snap["params"]
        names_changed = set(new) != set(self._params)
        changed = [n for n, p in new.items()
                   if n in self._params and self._params[n]["value"] != p["value"]]
        self._params = new
        if names_changed:
            dropped = [n for n in self._pending if n not in new]
            for n in dropped:
                self._pending.pop(n, None)
                self._errors.pop(n, None)
            if dropped:
                self.pendingChanged.emit()
            self._rebuild_groups()
            self._rebuild_rows()
            self.viewChanged.emit()
        elif changed:
            self._model.touch(changed)
        state = (snap["state"], snap["message"], snap["received"], snap["total"])
        if state != (self._state, self._message, self._received, self._total):
            self._state, self._message, self._received, self._total = state
            self.stateChanged.emit()

    # ---- properties ----------------------------------------------------------------

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(bool, constant=True)
    def available(self) -> bool:
        return self._mgr is not None

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=stateChanged)
    def message(self) -> str:
        return self._message

    @Property(int, notify=stateChanged)
    def received(self) -> int:
        return self._received

    @Property(int, notify=stateChanged)
    def total(self) -> int:
        return self._total

    @Property(int, notify=viewChanged)
    def count(self) -> int:
        return len(self._params)

    @Property(int, notify=viewChanged)
    def shown(self) -> int:
        return len(self._model.rows())

    @Property("QVariantList", notify=viewChanged)
    def groups(self) -> list:
        return list(self._groups)

    @Property(str, notify=viewChanged)
    def group(self) -> str:
        return self._group

    @Property(str, notify=viewChanged)
    def filter(self) -> str:
        return self._filter

    @Property(bool, notify=viewChanged)
    def modifiedOnly(self) -> bool:
        return self._modified_only

    @Property(int, notify=pendingChanged)
    def pendingCount(self) -> int:
        return len(self._pending)

    @Property(int, notify=pendingChanged)
    def errorCount(self) -> int:
        return len(self._errors)

    @Property(bool, notify=writeChanged)
    def writing(self) -> bool:
        return self._writing

    @Property(int, notify=writeChanged)
    def writeDone(self) -> int:
        return self._write_done

    @Property(int, notify=writeChanged)
    def writeTotal(self) -> int:
        return self._write_total

    @Property(int, notify=writeChanged)
    def writeOk(self) -> int:
        return self._write_ok

    # ---- view slots ----------------------------------------------------------------

    @Slot(str)
    def setFilter(self, text: str) -> None:
        self._filter = (text or "").strip()
        self._rebuild_rows()
        self.viewChanged.emit()

    @Slot(str)
    def setGroup(self, group: str) -> None:
        self._group = "" if group == self._group else (group or "")
        self._rebuild_rows()
        self.viewChanged.emit()

    @Slot(bool)
    def setModifiedOnly(self, on: bool) -> None:
        self._modified_only = bool(on)
        self._rebuild_rows()
        self.viewChanged.emit()

    # ---- loading -------------------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        if self._mgr is None or self._writing:
            return
        self._mgr.request_all()
        self._poll()

    @Slot()
    def ensureLoaded(self) -> None:
        """Window opened: download once if nothing is cached for this vehicle."""
        if self._mgr is not None and not self._params and self._state in ("idle", "error"):
            self.refresh()

    @Slot(str)
    def refreshOne(self, name: str) -> None:
        if self._mgr is not None:
            self._mgr.refresh(name)

    # ---- staging -------------------------------------------------------------------

    def _parse(self, name: str, text: str):
        p = self._params.get(name)
        if p is None:
            raise ValueError("Unknown parameter")
        t = (text or "").strip()
        if not t:
            raise ValueError("Enter a value")
        if self._P.is_integer_type(p["type"]):
            try:
                value = int(t, 0)               # accepts 0x.. for bitmasks
            except ValueError:
                f = float(t)
                if f != int(f):
                    raise ValueError("This parameter takes a whole number")
                value = int(f)
        else:
            value = float(t)
        self._P.encode_value(value, p["type"], False)   # range / finite check
        return value

    @Slot(str, str, result="QVariantMap")
    def stage(self, name: str, text: str) -> dict:
        p = self._params.get(name)
        try:
            value = self._parse(name, text)
        except (TypeError, ValueError) as exc:
            msg = str(exc)
            if msg.startswith("could not convert") or msg.startswith("invalid literal"):
                msg = "Not a number"
            return {"ok": False, "error": msg}
        if self._P.values_equal(value, p["value"], p["type"]):
            self.unstage(name)
            return {"ok": True, "error": ""}
        self._pending[name] = value
        self._errors.pop(name, None)
        self._model.touch([name])
        self.pendingChanged.emit()
        return {"ok": True, "error": ""}

    @Slot(str)
    def unstage(self, name: str) -> None:
        had = self._pending.pop(name, None) is not None
        self._errors.pop(name, None)
        if had:
            self._model.touch([name])
            if self._modified_only:
                self._rebuild_rows()
                self.viewChanged.emit()
            self.pendingChanged.emit()

    @Slot()
    def discardAll(self) -> None:
        if self._writing:
            return
        names = list(self._pending)
        self._pending.clear()
        self._errors.clear()
        self._model.touch(names)
        if self._modified_only:
            self._rebuild_rows()
            self.viewChanged.emit()
        self.pendingChanged.emit()

    # ---- writing -------------------------------------------------------------------

    @Slot()
    def writeAll(self) -> None:
        if self._mgr is None or self._writing or not self._pending:
            return
        jobs = sorted(self._pending.items())
        self._writing, self._write_done, self._write_total, self._write_ok = True, 0, len(jobs), 0
        self.writeChanged.emit()

        def run() -> None:
            for name, value in jobs:
                res = self._mgr.set_param(name, value)
                with self._results_lock:
                    self._results.append((name, res))
                if res.get("error", "").startswith("Vehicle is armed") or res.get("error") == "No vehicle link":
                    # Same answer for every remaining edit: stop, keep them staged.
                    with self._results_lock:
                        self._results.append(("__stop__", res))
                    break
            with self._results_lock:
                self._results.append(("__done__", {}))

        threading.Thread(target=run, daemon=True, name="param-write").start()

    def _apply_write_results(self) -> None:
        with self._results_lock:
            results, self._results = self._results, []
        if not results:
            return
        touched = []
        for name, res in results:
            if name == "__done__":
                self._writing = False
                continue
            if name == "__stop__":
                for n in self._pending:
                    if n not in self._errors:
                        self._errors[n] = res.get("error", "Stopped")
                        touched.append(n)
                continue
            self._write_done += 1
            if res.get("ok"):
                self._write_ok += 1
                self._pending.pop(name, None)
                self._errors.pop(name, None)
            else:
                self._errors[name] = res.get("error", "Failed")
            touched.append(name)
        self._model.touch(touched)
        if self._modified_only:
            self._rebuild_rows()
            self.viewChanged.emit()
        self.pendingChanged.emit()
        self.writeChanged.emit()

    # ---- files -----------------------------------------------------------------------

    @Slot(str, result="QVariantMap")
    def exportTo(self, url: str) -> dict:
        if not self._params:
            return {"ok": False, "error": "Nothing to export — load parameters first"}
        path = _local_path(url)
        if path.suffix == "":
            path = path.with_suffix(".params")
        m = self._mgr._master() if self._mgr is not None else None
        sysid = int(getattr(m, "target_system", 1) or 1) if m else 1
        compid = int(getattr(m, "target_component", 1) or 1) if m else 1
        try:
            path.write_text(self._P.export_text(self._params, sysid, compid))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": "", "path": str(path), "count": len(self._params)}

    @Slot(str, result="QVariantMap")
    def importFrom(self, url: str) -> dict:
        if not self._params:
            return {"ok": False, "error": "Load the vehicle's parameters first"}
        path = _local_path(url)
        try:
            values = self._P.parse_text(path.read_text(errors="replace"))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if not values:
            return {"ok": False, "error": "No parameters found in that file"}
        staged = unknown = same = bad = 0
        for name, value in values.items():
            p = self._params.get(name)
            if p is None:
                unknown += 1
                continue
            res = self.stage(name, repr(int(value)) if self._P.is_integer_type(p["type"]) and value == int(value) else repr(value))
            if not res["ok"]:
                bad += 1
            elif name in self._pending:
                staged += 1
            else:
                same += 1
        return {"ok": True, "error": "", "staged": staged, "unchanged": same,
                "unknown": unknown, "invalid": bad}
